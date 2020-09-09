import time

import requests
import yaml
import logging
from multiprocessing.pool import ThreadPool
from itertools import repeat
from parse_prome_query_log import recovery_concurrent_log_parse

logging.basicConfig(
    # TODO console 日志,上线时删掉
    # filename=LOG_PATH,
    format='%(asctime)s %(levelname)s %(filename)s %(funcName)s [line:%(lineno)d]:%(message)s',
    datefmt="%Y-%m-%d %H:%M:%S",
    level="INFO"
)


def load_yaml(yal_path=r'C:\Users\Administrator\Desktop\record_2202_2020-04-29_23-30-24.yml'):
    f = open(yal_path)
    y = yaml.load(f)

    all_heavy = y.get("groups")[0].get("rules")
    msg = "get {} heavy_record".format(len(all_heavy))
    logging.info(msg)
    return all_heavy


def query_range(host, expr, key):
    '''

    :param host:
    :param expr:
    调用举例: 获取group=ugc的project

    query_range(inf,
            'avg(100 - (avg by (instance,name) (rate(node_cpu_seconds_total{region=~"ap-southeast-3",account=~"HW-SHAREit",group=~"UGC",project=~"cassandra-client",name=~"UGC-cassandra-client-prod", mode="idle"}[5m])) * 100))')


    :return:
    {
        "status":"success",
        "data":{
            "resultType":"matrix",
            "result":[
                {
                    "metric":{

                    },
                    "values":[
                        [
                            1588149960,
                            "0.1999999996688473"
                        ],
                        [
                            1588150020,
                            "0.20000000035872745"
                        ],
                        [
                            1588150080,
                            "0.19629629604793308"
                        ],
                        [
                            1588150140,
                            "0.19629629673781324"
                        ],
                        [
                            1588150200,
                            "0.1999999996688473"
                        ],
                        [
                            1588150260,
                            "0.2074074076005843"
                        ]
                    ]
                }
            ]
        }
    }
    '''
    # logging.info("host:{} expr:{}".format(host, expr))
    uri = '{}/api/v1/query_range'.format(host)

    end = int(time.time())
    start = end - 60 * 60

    G_PARMS = {
        "query": expr,
        "start": start,
        "end": end,
        "step": 30
    }
    res = requests.get(uri, G_PARMS)
    data = res.json()
    now = int(time.time())
    took = now - end
    if took > 4:
        return (key, True)
    return (key, False)


def concurrency_query():
    t_num = 20
    pool = ThreadPool(t_num)
    yaml_data = load_yaml()
    all_expr = [x.get("expr") for x in yaml_data][:100]
    all_key = [x.get("record") for x in yaml_data][:100]
    host = "http://localhost:9999"

    pars = zip(repeat(host), all_expr, all_key)
    results = pool.starmap(query_range, pars)

    pool.close()
    pool.join()
    for x in results:
        print(x)


def recovery(yaml_path):
    yaml_data = load_yaml(yal_path=yaml_path)
    res_dic = {}

    for x in yaml_data:
        res_dic[x.get("record")] = x.get("expr")

    recovery_concurrent_log_parse(res_dic)
    # purge consul

    # purge redis


if __name__ == '__main__':
    import sys

    yaml_path = sys.argv[1]
    recovery(yaml_path)
