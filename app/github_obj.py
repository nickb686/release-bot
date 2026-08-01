from github import Auth, Github

from config import settings

auth = Auth.Token(settings.GITHUB_TOKEN) if settings.GITHUB_TOKEN else None
github_obj = Github(auth=auth)
