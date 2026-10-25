"""Shared monitoring extensions must remain additive and namespace bounded."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT=Path(__file__).resolve().parents[1]


class MonitoringIntegration(unittest.TestCase):
    def render(self, integration):
        with tempfile.TemporaryDirectory() as folder:
            values=Path(folder)/'project.yaml';values.write_text(yaml.safe_dump({'integration':integration}))
            output=subprocess.check_output(['helm','template','shared',str(ROOT/'monitoring'),'-f',str(ROOT/'monitoring/profiles/homelab/values.yaml'),'-f',str(values)],text=True,stderr=subprocess.PIPE)
            return [d for d in yaml.safe_load_all(output) if d]

    def fixture(self):
        return {'namespaces':['commerce-dev','commerce-qa'],
                'scrapeConfigs':[{'job_name':'narx-test','static_configs':[{'targets':['example.invalid:8080']}]}],
                'ruleGroups':[{'name':'narx-test','rules':[{'alert':'NarxTest','expr':'vector(0) > 1'}]}],
                'dashboards':{'narx-test':{'uid':'narx-test','title':'Narx test','panels':[]}}}

    def test_extensions_preserve_existing_jobs_rules_and_dashboard_mounts(self):
        docs=self.render(self.fixture())
        cm=next(d for d in docs if d['kind']=='ConfigMap' and d['metadata']['name']=='boutique-prometheus')
        config=yaml.safe_load(cm['data']['prometheus.yml'])
        names={j['job_name'] for j in config['scrape_configs']}
        self.assertTrue({'boutique','orders','prometheus','narx-test'} <= names)
        rules=yaml.safe_load(cm['data']['rules.yml'])
        self.assertIn('narx-test',{g['name'] for g in rules['groups']})
        self.assertIn('project="boutique"',cm['data']['rules.yml'])
        grafana=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='grafana')
        mounts=grafana['spec']['template']['spec']['containers'][0]['volumeMounts']
        self.assertIn('narx-test.json',{m.get('subPath') for m in mounts})
        self.assertIn('boutique.json',{m.get('subPath') for m in mounts})
        roles=[d for d in docs if d['kind']=='Role' and d['metadata']['name']=='monitoring-pod-discovery']
        self.assertEqual({d['metadata']['namespace'] for d in roles},{'boutique-dev','boutique-staging','boutique-production','commerce-dev','commerce-qa','monitoring','monitoring-logs'})
        alloy=next(d for d in docs if d['kind']=='ConfigMap' and d['metadata']['name']=='boutique-alloy')['data']['config.alloy']
        self.assertIn('commerce-qa',alloy)
        self.assertIn('replacement = "narx-commerce"',alloy)

    def test_qa_routes_to_slack_and_project_isolation_is_preserved(self):
        docs=self.render(self.fixture())
        cm=next(d for d in docs if d['kind']=='ConfigMap' and d['metadata']['name']=='boutique-alertmanager')
        config=yaml.safe_load(cm['data']['alertmanager.yml'])
        self.assertIn('project',config['route']['group_by'])
        self.assertIn('project',config['inhibit_rules'][0]['equal'])
        self.assertIn('environment=~"dev|qa|staging"',config['route']['routes'][-1]['matchers'])
        for receiver in config['receivers']:
            self.assertTrue(receiver['slack_configs'][0]['api_url_file'].startswith('/run/secrets/'))
            self.assertNotIn('api_url',receiver['slack_configs'][0])

    def test_integration_cannot_grant_discovery_of_system_namespaces(self):
        values=self.fixture();values['namespaces']=['kube-system']
        with self.assertRaises(subprocess.CalledProcessError):self.render(values)

    def test_dashboard_names_cannot_escape_the_dashboard_directory(self):
        values=self.fixture();values['dashboards']={'../escape':{'uid':'escape','title':'Bad'}}
        with self.assertRaises(subprocess.CalledProcessError):self.render(values)


if __name__=='__main__':unittest.main()
