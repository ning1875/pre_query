import json

import consul
import time

import redis


class Consul(object):
    def __init__(self, host, port):
        '''初始化，连接consul服务器'''
        self._consul = consul.Consul(host, port)

    def RegisterService(self, name, service_id, host, port, check_url, tags=None):
        tags = tags or []
        # 注册服务
        self._consul.agent.service.register(
            name,
            service_id,
            host,
            port,
            tags,
            # 健康检查ip端口，检查时间：5,超时时间：30，注销时间：30s
            check=consul.Check().http(check_url, "5s", "5s"))

    def GetService(self, name):
        res = self._consul.health.service(name, passing=True)
        print(res)
        # services = self._consul.agent.services()
        # print(services)
        # service = services.get(name)
        #
        # if not service:
        #     return None, None
        # addr = "{0}:{1}".format(service['Address'], service['Port'])
        # return service, addr

    def delete_key(self, key='prometheus/records'):
        res = self._consul.kv.delete(key, recurse=True)
        return res

    def get_key_by_record(self, key='prometheus/records', record=""):
        res = self._consul.kv.get(key, recurse=True)
        data = res[1]
        if not data:
            return None

        for i in data:
            key = i.get("Key")

            v = json.loads(i.get('Value').decode("utf-8"))
            if record in v.get('record'):
                print(key, v.get('record'), v.get('expr'))
                return key
        return None


def redis_conn():
    redis_host = "localhost"

    redis_port = 6379
    conn = redis.Redis(host=redis_host, port=redis_port)
    return conn


def delete_key():
    to_del_keys = []
    with open('to_del_record_key_file') as f:
        to_del_keys = [x.strip() for x in f.readlines()]
    print(to_del_keys)

    host = 'localhost'
    port = 8500

    consul_record_key_prefix = 'prometheus/records'
    consul_client = Consul(host, port)
    redis_c = redis_conn()

    for key in to_del_keys:
        if not key:
            continue
        to_del_key = consul_client.get_key_by_record(record=key)
        print(to_del_key)
        if to_del_key:
            consul_client.delete_key(to_del_key)
            redis_key = "hke:heavy_expr:{}".format(key)
            delete_res = redis_c.delete(redis_key)
            print(delete_res)


def run_register():
    host = 'localhost'
    port = 8500
    consul_client = Consul(host, port)

    s_name = "pushgateway_a"
    s_hosts = [
        'localhost',
    ]

    s_port = 9091

    for h in s_hosts:
        s_check_url = 'http://{}:{}/-/healthy'.format(h, s_port)
        # consul_client.RegisterService(s_name, h, h, s_port, s_check_url)
        # check = consul.Check().http(s_check_url, "5s", "5s", "5s")
        # print(check)

    res = consul_client._consul.agent.service.deregister(s_name)
    print(res)
    res = consul_client.GetService(s_name)
    # print(res[0])


def run_query():
    host = 'localhost'
    port = 8500
    consul_record_key_prefix = 'prometheus/records'
    consul_client = Consul(host, port)


if __name__ == '__main__':
    # run_register()
    # run_query()
    delete_key()
