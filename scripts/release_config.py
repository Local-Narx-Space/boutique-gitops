"""Shared GitOps image selection and history helpers."""
import re
import subprocess
from pathlib import Path
SERVICES = ('frontend','catalogue','cart','orders')
ENVIRONMENTS = ('dev','staging','production')
ROOT = Path(__file__).resolve().parents[1]
class ReleaseError(ValueError):
    pass

def validate_identity(service, environment, image):
    if service not in SERVICES or environment not in ENVIRONMENTS:
        raise ReleaseError('Invalid service or environment')
    if not re.fullmatch(rf'ghcr\.io/subhankar12-spec/boutique-{service}@sha256:[a-f0-9]{{64}}',image):
        raise ReleaseError('Expected immutable service image digest')

def git(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True)
    if result.returncode:
        raise ReleaseError("GitOps commit is unavailable or not in trusted history")
    return result.stdout.strip()


def overlay(service, environment):
    return f"environments/{environment}/releases.yaml"


def selected_image(root, service, environment, commit=None):
    from helm_release import load, values_path
    data=load(root,values_path(environment),commit)
    if not isinstance(data,dict) or set(data)!=set(SERVICES):
        raise ReleaseError("Helm release values require exactly the four services")
    for name, configuration in data.items():
        if not isinstance(configuration,dict) or set(configuration)!={"image"}:
            raise ReleaseError("Release values can change only service image selections")
        image=configuration["image"]
        if not isinstance(image,dict) or set(image)!={"repository","digest","tag"}:
            raise ReleaseError("Invalid Helm image selection")
    image=data[service]["image"]
    if image["digest"]:
        if image["tag"]:raise ReleaseError("An immutable image selection cannot also specify a tag")
        return image["repository"]+"@"+image["digest"]
    return image["repository"]+":"+image["tag"]


def validation_environments(root, base=None):
    """Scope clean release-only commits; everything else needs full validation."""
    if not base:
        return None
    try:
        if git(root, 'status', '--porcelain'):
            return None
        git(root, 'merge-base', '--is-ancestor', base, 'HEAD')
        paths = [p for p in git(root, 'diff', '--name-only', '-z', '--no-renames', base, 'HEAD').split('\0') if p]
    except ReleaseError:
        return None
    release_path = re.compile(
        r'environments/(dev|staging|production)/(?:Chart\.yaml|releases\.yaml|'
        r'charts/boutique-(?:frontend|catalogue|cart|orders)-0\.1\.0-[a-f0-9]{40}\.tgz)')
    matches = [release_path.fullmatch(path) for path in paths]
    if not matches or not all(matches):
        return None
    changed = {match.group(1) for match in matches}
    return tuple(env for env in ENVIRONMENTS if env in changed)
