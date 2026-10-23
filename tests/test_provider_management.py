"""Only temporary encrypted configuration and fictional local suppliers."""
from datetime import datetime,timezone
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
from tests import test_configured_tasks as configured
from tests import test_custom_provider_http as http_fixture
from test_custom_providers import wire
from novel_writer.application.provider_catalog import catalog,estimate
from novel_writer.application.provider_connections import ProviderConnections,PROVIDERS

class ProviderManagementTests(unittest.TestCase):
    setUp=configured.ConfiguredTaskTests.setUp
    save=configured.ConfiguredTaskTests.save
    prepare=configured.ConfiguredTaskTests.prepare
    def manage(self,id,action,**values):return self.providers.manage(id=id,action=action,confirmed=True,**values)
    def test_disable_reenable_expires_frozen_task_and_new_task_can_execute(self):
        with wire('openai-chat') as (endpoint,calls):
            saved=self.save(endpoint);task=self.prepare(saved)['task'];b=task['frozen']['parameters']['binding'];confirm=dict(confirm_external=True,request_sha256=b['request_sha256'])
            self.manage(saved['id'],'disable')
            with self.assertRaisesRegex(ValueError,'禁用'):self.engine.start(self.pid,task['id'],confirm)
            self.assertEqual(calls,[])
            self.manage(saved['id'],'enable')
            with self.assertRaisesRegex(ValueError,'过期|已变化'):self.engine.start(self.pid,task['id'],confirm)
            task=self.prepare(saved)['task'];b=task['frozen']['parameters']['binding'];self.engine.start(self.pid,task['id'],dict(confirm_external=True,request_sha256=b['request_sha256']));self.engine.wait_idle(5)
            self.assertEqual(len(calls),1);self.assertEqual(self.engine.describe(self.pid,task['id'])['task']['status'],'succeeded')
            self.assertEqual(self.service.get(self.pid)['document']['chapters'][0]['content'],'作者保存的虚构原稿。')
    def test_delete_only_selected_credentials_disables_persists_and_has_no_plaintext(self):
        first=self.save('https://provider.example/v1');second=self.save('https://other.example/v1')
        self.manage(first['id'],'delete_credentials')
        reopened=ProviderConnections(self.providers.path);status=reopened.status()
        self.assertFalse(status[first['id']]['key_configured']);self.assertFalse(status[first['id']]['enabled']);self.assertTrue(status[second['id']]['key_configured'])
        self.assertNotIn('fiction-configured-key',json.dumps(status));self.assertNotIn(b'fiction-configured-key',self.providers.path.read_bytes())
        with self.assertRaises(ValueError):self.providers.manage(id=second['id'],action='disable',confirmed=False)
        # Public connection without credentials must be explicitly replenished.
        public=self.providers.save_custom(id=str(uuid4()),name='公开虚构',base_url='https://public.example/v1',protocol='openai-chat',model_id='fiction-model',api_key='fiction-key',allow_local=False)
        self.manage(public['id'],'delete_credentials')
        with self.assertRaisesRegex(ValueError,'凭据已删除'):self.manage(public['id'],'enable')
    def test_local_limits_reserve_failed_attempts_and_refuse_before_transport(self):
        with wire('openai-chat') as (endpoint,calls):
            saved=self.save(endpoint);self.manage(saved['id'],'limits',min_interval_ms=1000,requests_per_minute=1)
            destination=self.providers.destination(saved['id'],'fiction-model')
            self.providers.generation_connection(saved['id'],'fiction-model',enabled=True,confirmed=True,destination=destination)
            with self.assertRaisesRegex(ValueError,'限流'):self.providers.generation_connection(saved['id'],'fiction-model',enabled=True,confirmed=True,destination=destination)
            self.assertEqual(calls,[])
            for values in (dict(min_interval_ms=True,requests_per_minute=1),dict(min_interval_ms=0,requests_per_minute=-1)):
                with self.assertRaises(ValueError):self.manage(saved['id'],'limits',**values)
    def test_legacy_connection_management_invalidates_prepared_timestamp(self):
        self.providers.save(id='gg',base_url=PROVIDERS['gg']['base_url'],model_id='fiction',api_key='fiction-legacy')
        before=datetime.now(timezone.utc).isoformat();self.manage('gg','disable')
        with self.assertRaisesRegex(ValueError,'禁用'):self.providers.generation_connection('gg','fiction',enabled=True,confirmed=True)
        self.manage('gg','enable')
        with self.assertRaisesRegex(ValueError,'过期'):ProviderConnections(self.providers.path).assert_prepared('gg',before)
    def test_catalog_unknown_prices_and_explicit_manual_estimate(self):
        data=catalog();self.assertEqual(data['price_status'],'unknown');self.assertIsNone(data['prices']);self.assertTrue(data['source']);self.assertEqual(len(data['protocols']),3)
        values=dict(input_tokens=1000000,output_tokens=500000,input_per_million=2,output_per_million=4,currency='usd')
        result=estimate(values);self.assertEqual(result['amount'],4);self.assertEqual(result['price_status'],'manual_estimate');self.assertFalse(result['model_request_sent'])
        for patch in ({'input_tokens':True},{'output_tokens':1.5},{'input_per_million':float('inf')},{'currency':'<script>'}):
            with self.assertRaises(ValueError):estimate({**values,**patch})

class ProviderManagementHTTPTests(unittest.TestCase):
    setUp=http_fixture.CustomProviderHttpTests.setUp
    stop=http_fixture.CustomProviderHttpTests.stop
    request=http_fixture.CustomProviderHttpTests.request
    def test_manage_catalog_estimate_and_token(self):
        fields=dict(id=str(uuid4()),name='虚构HTTP',base_url='https://fiction.example/v1',protocol='openai-chat',model_id='fiction-model',api_key='fiction-only-sentinel',allow_local=False)
        self.assertEqual(self.request('POST','/api/providers/custom',fields)[0],201)
        payload=dict(id=fields['id'],action='disable',confirmed=True)
        self.assertEqual(self.request('POST','/api/providers/manage',payload,token=False)[0],403)
        code,result=self.request('POST','/api/providers/manage',payload);self.assertEqual(code,200);self.assertFalse(result['enabled'])
        self.assertEqual(self.request('POST','/api/providers/test',dict(id=fields['id']))[0],422)
        self.assertEqual(self.request('GET','/api/providers/catalog')[1]['price_status'],'unknown')
        code,result=self.request('POST','/api/providers/estimate',dict(input_tokens=1000,output_tokens=1000,input_per_million=1,output_per_million=2,currency='USD'));self.assertEqual(code,200);self.assertEqual(result['amount'],.003)
        self.assertNotIn(fields['api_key'],json.dumps(self.request('GET','/api/settings')[1]))
