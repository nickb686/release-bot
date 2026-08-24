import contextlib
from datetime import UTC, datetime, timedelta

from github import GithubException
from github.Repository import Repository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Repo
from app.database.models.release import Release


async def store_latest_release(
    session: AsyncSession,
    github_repo: Repository,
    repo: Repo,
    process_pre_release: bool,
):
    release = None
    prerelease = None
    tag = None

    if process_pre_release:
        releases = github_repo.get_releases()
        with contextlib.suppress(IndexError):
            prerelease = releases[0]

        if prerelease and (not prerelease.prerelease or prerelease.draft):
            prerelease = None
        if (
            prerelease
            and datetime.now(UTC) - timedelta(minutes=15) < prerelease.published_at
        ):
            prerelease = None

    try:
        release = github_repo.get_latest_release()
        if release.draft:
            release = None
    except GithubException:
        # Repo has no releases yet
        if github_repo.get_tags().totalCount > 0:
            tag = github_repo.get_tags()[0]

    if release or prerelease:
        if release:
            release.updated = False  # pyrefly: ignore [missing-attribute]
            release_obj = await session.scalar(
                select(Release).where(
                    Release.repo_id == github_repo.id,
                    Release.release_id == release.id,
                ),
            )
            if release_obj and release_obj.release_date:
                stored_release_date = release_obj.release_date.replace(tzinfo=UTC)
                if (
                    release.last_modified_datetime
                    and release.last_modified_datetime > stored_release_date
                ):
                    release_obj.release_date = release.last_modified_datetime
                    release_obj.pre_release = release.prerelease
                    await session.commit()

                    release.updated = True  # pyrefly: ignore [missing-attribute]
                else:
                    release = None
            else:
                release_obj = Release(
                    release_id=release.id,
                    tag_name=release.tag_name,
                    release_date=release.last_modified_datetime,
                    link=release.html_url,
                    pre_release=release.prerelease,
                )
                repo.releases.append(release_obj)
                await session.commit()

        if prerelease:
            prerelease.updated = False  # pyrefly: ignore [missing-attribute]
            release_obj = await session.scalar(
                select(Release).where(
                    Release.repo_id == github_repo.id,
                    Release.release_id == prerelease.id,
                ),
            )
            if not release_obj:
                release_obj = Release(
                    release_id=prerelease.id,
                    tag_name=prerelease.tag_name,
                    release_date=prerelease.published_at,
                    link=prerelease.html_url,
                    pre_release=prerelease.prerelease,
                )
                repo.releases.append(release_obj)
                await session.commit()
            else:
                prerelease = None

        return release, prerelease
    if tag:
        release_obj = await session.scalar(
            select(Release).where(
                Release.repo_id == github_repo.id,
                Release.tag_name == tag.name,
            ),
        )
        if not release_obj:
            release_obj = Release(
                tag_name=tag.name,
                release_date=tag.last_modified_datetime,
            )
            repo.releases.append(release_obj)
            await session.commit()
            return tag, None

    return None, None
