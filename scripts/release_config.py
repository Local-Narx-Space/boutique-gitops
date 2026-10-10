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

