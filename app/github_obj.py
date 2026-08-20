from github import Auth, Github

from config import settings

auth = (
    Auth.Token(settings.service.GITHUB_TOKEN) if settings.service.GITHUB_TOKEN else None
)
github_obj = Github(auth=auth)
