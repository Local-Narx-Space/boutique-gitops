"""Helm release selection and Git-pinned dependency packages.

Argo renders the reviewed packages committed with the environment. OCI copies
are distribution artifacts; a mutable registry tag cannot change a merged tree.
"""
import hashlib
import io
import re
import tarfile
from pathlib import Path, PurePosixPath

import yaml
from release_config import ReleaseError, git

SERVICES = ('frontend','catalogue','cart','orders')
REPOSITORY = 'oci://ghcr.io/subhankar12-spec/charts'


def load(root, relative, commit=None, binary=False):
    if commit:
        if binary:
            import subprocess
            result=subprocess.run(['git','-C',str(root),'show',f'{commit}:{relative}'],capture_output=True)
            if result.returncode:raise ReleaseError('Chart package unavailable in trusted Git history')
            return result.stdout
        return yaml.safe_load(git(root,'show',f'{commit}:{relative}'))
    p=Path(root)/relative
    if p.is_symlink():raise ReleaseError('Helm inputs cannot be symbolic links')
    return p.read_bytes() if binary else yaml.safe_load(p.read_text())


def values_path(environment):
    return f'environments/{environment}/releases.yaml'


def dependency(root, service, environment, commit=None):
    chart=load(root,f'environments/{environment}/Chart.yaml',commit)
    dependencies=chart.get('dependencies',[])
    if len(dependencies)!=4 or {d.get('alias') for d in dependencies}!=set(SERVICES):
        raise ReleaseError('Environment requires exactly the four approved service charts')
    for d in dependencies:
        if set(d)!={'name','alias','version','repository'} or d['name']!='boutique-'+d['alias'] or d['repository']!=REPOSITORY:
            raise ReleaseError('Unapproved Helm dependency identity or repository')
        if not re.fullmatch(r'0\.1\.0-(?:bootstrap|[a-f0-9]{40})',d['version']):
            raise ReleaseError('Helm dependencies require source-SHA versions')
    return next(d for d in dependencies if d['alias']==service)


def package_path(service, environment, version):
    return f'environments/{environment}/charts/boutique-{service}-{version}.tgz'


def inspect_package(data, service, version):
    if len(data)>2*1024*1024:raise ReleaseError('Chart package exceeds 2 MiB')
    prefix='boutique-'+service
    try:
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            members=archive.getmembers()
            if len(members)>256 or len({member.name for member in members})!=len(members):
                raise ReleaseError("Chart package contains too many or duplicate entries")
            total=0
            for member in members:
                path=PurePosixPath(member.name)
                total+=member.size
                if total>8*1024*1024 or path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!=prefix or not member.isfile():
                    raise ReleaseError('Chart package contains unsafe or unexpected entries')
            chart=yaml.safe_load(archive.extractfile(prefix+'/Chart.yaml').read())
            if chart.get('apiVersion')!='v2' or chart.get('name')!=prefix or chart.get('version')!=version or chart.get('dependencies'):
                raise ReleaseError('Chart package metadata does not match the selected release')
            if any('/charts/' in m.name for m in archive.getmembers()):
                raise ReleaseError('Nested dependencies are not approved in service charts')
    except (tarfile.TarError,KeyError,AttributeError,UnicodeError) as error:
        raise ReleaseError('Invalid Helm chart package') from error
    return hashlib.sha256(data).hexdigest()


def selected_chart(root, service, environment, commit=None):
    d=dependency(root,service,environment,commit)
    data=load(root,package_path(service,environment,d['version']),commit,binary=True)
    sha=inspect_package(data,service,d['version'])
    return {'name':d['name'],'repository':d['repository'],'version':d['version'],'package_sha256':sha}


def select_release(root, service, environment, image, version, package):
    """Update a reviewed image digest and its exact packaged Helm chart."""
    from release_config import validate_identity
    validate_identity(service, environment, image)
    if not re.fullmatch(r'0\.1\.0-[a-f0-9]{40}', version):
        raise ReleaseError('Select a source-SHA chart version, not bootstrap')
    inspect_package(package, service, version)
    values = load(root, values_path(environment))
    chart = load(root, f'environments/{environment}/Chart.yaml')
    dependency(root, service, environment)
    old = next(d for d in chart['dependencies'] if d['alias'] == service)
    previous = Path(root) / package_path(service, environment, old['version'])
    new = Path(root) / package_path(service, environment, version)
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_bytes(package)
    if previous != new and previous.exists():
        previous.unlink()
    old['version'] = version
    values[service] = {'image': {'repository': image.split('@')[0], 'digest': image.split('@')[1], 'tag': ''}}
    (Path(root) / f'environments/{environment}/Chart.yaml').write_text(yaml.safe_dump(chart, sort_keys=False))
    (Path(root) / values_path(environment)).write_text(yaml.safe_dump(values, sort_keys=False))

def approved_argo_source(source, environment):
    from render import value_files
    if not isinstance(source,dict) or source.get('repoURL')!='https://github.com/subhankar12-spec/boutique-gitops.git' or source.get('targetRevision')!='main' or source.get('path')!=f'environments/{environment}':
        raise ReleaseError('Argo must use the approved Helm environment on GitOps main')
    if set(source)!={'repoURL','targetRevision','path','helm'}:
        raise ReleaseError('Unapproved Argo source overrides')
    helm=source.get('helm')
    if not isinstance(helm,dict) or set(helm)!={'releaseName','valueFiles'} or helm['releaseName']!='boutique-'+environment or helm['valueFiles'] not in ([value_files(environment,'cloud'),value_files(environment,'lab')] + ([value_files(environment,'laptop')] if environment == 'dev' else [])):
        raise ReleaseError('Argo must use approved Helm values without inline overrides')
