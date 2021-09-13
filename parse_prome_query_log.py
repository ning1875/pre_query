import base64
import glob
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from multiprocessing.pool import ThreadPool

import consul
import redis
import requests
import yaml

from libs import get_str_md5, load_base_config, now_date_str

logging.basicConfig(
    # TODO console 日志,上线时删掉
    # filename=LOG_PATH,
    format='%(asctime)s %(levelname)s %(filename)s %(funcName)s [line:%(lineno)d]:%(message)s',
    datefmt="%Y-%m-%d %H:%M:%S",
    level="INFO"
)
G_VAR_YAML = "config.yaml"


class Consul(object):
    def __init__(self, host, port):
        '''初始化，连接consul服务器'''
        self._consul = consul.Consul(host, port)

    def RegisterService(self, name, host, port, tags=None):
        tags = tags or []
        # 注册服务
        self._consul.agent.service.register(
            name,
            name,
            host,
            port,
            tags,
            # 健康检查ip端口，检查时间：5,超时时间：30，注销时间：30s
            check=consul.Check().tcp(host, port, "5s", "30s", "30s"))

    def GetService(self, name):
        services = self._consul.agent.services()
        service = services.get(name)
        if not service:
            return None, None
        addr = "{0}:{1}".format(service['Address'], service['Port'])
        return service, addr

    def delete_key(self, key='prometheus/records'):
        res = self._consul.kv.delete(key, recurse=True)
        return res

    def get_list(self, key='prometheus/records'):
        res = self._consul.kv.get(key, recurse=True)

        data = res[1]
        if not data:
            return {}
        pre_record_d = {}

        for i in data:
            v = json.loads(i.get('Value').decode("utf-8"))
            pre_record_d[v.get('record')] = v.get('expr')
        return pre_record_d

    def set_data(self, key, value):
        '''
        self._consul.kv.put('prometheus/records/1',

                            json.dumps(
                                {

                                    "record": "nyy_record_test_a",
                                    "expr": 'sum(kafka_log_log_size{project=~"metis - main1 - sg2"}) by (topic)'
                                }
                            )
                            )
        '''
        self._consul.kv.put(key, value)

    def get_b64encode(self, message):
        message_bytes = message.encode('ascii')
        base64_bytes = base64.b64encode(message_bytes)
        return base64_bytes.decode("utf8")

    def txn_mset(self, record_expr_list):
        lens = len(record_expr_list)
        logging.info("top_lens:{}".format(lens))
        max_txn_once = 64
        yu_d = lens // max_txn_once
        yu = lens / max_txn_once

        if lens <= max_txn_once:
            pass
        else:
            max = yu_d

            if yu > yu_d:
                max += 1

            for i in range(0, max):
                sli = record_expr_list[i * max_txn_once:(i + 1) * max_txn_once]
                self.txn_mset(sli)
            return True
        '''
             {
                    "KV": {
                      "Verb": "<verb>",
                      "Key": "<key>",
                      "Value": "<Base64-encoded blob of data>",
                      "Flags": 0,
                      "Index": 0,
                      "Session": "<session id>"
                    }
                }

        :return:
        '''

        txn_data = []
        logging.info("middle_lens:{}".format(len(record_expr_list)))
        for index, data in record_expr_list:
            txn_data.append(
                {
                    "KV": {
                        "Key": "{}/{}".format(CONSUL_RECORD_KEY_PREFIX, index),
                        "Verb": "set",
                        "Value": self.get_b64encode(json.dumps(
                            data
                        )),

                    }
                }
            )
        # TODO local test
        # print(txn_data)
        # return True
        res = self._consul.txn.put(txn_data)
        if not res:
            logging.error("txn_mset_error")
            return False
        if res.get("Errors"):
            logging.error("txn_mset_error:{}".format(str(res.get("Errors"))))
            return False
        return True


def batch_delete_redis_key(conn, prefix):
    CHUNK_SIZE = 5000
    """
    Clears a namespace
    :param ns: str, namespace i.e your:prefix
    :return: int, cleared keys
    """
    cursor = '0'
    ns_keys = prefix + '*'
    while cursor != 0:
        cursor, keys = conn.scan(cursor=cursor, match=ns_keys, count=CHUNK_SIZE)
        if keys:
            conn.delete(*keys)

    return cursor


def redis_conn():
    redis_host = ONLINE_REDIS_HOST
    redis_port = ONLINE_REDIS_PORT
    conn = redis.Redis(host=redis_host, port=redis_port)
    return conn


def parse_log_file(log_f):
    '''
    {
    "httpRequest":{
        "clientIP":"1.1.1.1",
        "method":"GET",
        "path":"/api/v1/query_range"
    },
    "params":{
        "end":"2020-04-09T06:20:00.000Z",
        "query":"api_request_counter{job="kubernetes-pods",kubernetes_namespace="sprs",app="model-server"}/60",
        "start":"2020-04-02T06:20:00.000Z",
        "step":1200
    },
    "stats":{
        "timings":{
            "evalTotalTime":0.467329174,
            "resultSortTime":0.000476303,
            "queryPreparationTime":0.373947928,
            "innerEvalTime":0.092889708,
            "execQueueTime":0.000008911,
            "execTotalTime":0.467345411
        }
    },
    "ts":"2020-04-09T06:20:28.353Z"
    }
    :param log_f:
    :return:
    '''
    heavy_expr_set = set()
    heavy_expr_dict = dict()
    record_expr_dict = dict()

    with open(log_f) as f:
        for x in f.readlines():
            x = json.loads(x.strip())
            if not isinstance(x, dict):
                continue
            httpRequest = x.get("httpRequest")
            if not httpRequest:
                continue
            path = httpRequest.get("path")
            # 只处理path为query_range的
            if path != "/api/v1/query_range":
                continue
            params = x.get("params")
            if not params:
                continue
            start_time = params.get("start")
            end_time = params.get("end")
            stats = x.get("stats")
            if not stats:
                continue
            timings = stats.get("timings")
            if not timings:
                continue
            evalTotalTime = timings.get("evalTotalTime")
            execTotalTime = timings.get("execTotalTime")
            queryPreparationTime = timings.get("queryPreparationTime")
            execQueueTime = timings.get("execQueueTime")
            innerEvalTime = timings.get("innerEvalTime")

            # 如果查询事件段大于6小时则不认为是heavy-query
            if not start_time or not end_time:
                continue
            start_time = datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%S.%fZ').timestamp()
            end_time = datetime.strptime(end_time, '%Y-%m-%dT%H:%M:%S.%fZ').timestamp()
            if end_time - start_time > 3600 * 6:
                continue

            # 如果两个时间都小于阈值则不为heavy-query
            c = (queryPreparationTime < HEAVY_QUERY_THREHOLD) and (innerEvalTime < HEAVY_QUERY_THREHOLD)
            if c:
                continue

            if queryPreparationTime > 40:
                continue
            if execQueueTime > 40:
                continue
            if innerEvalTime > 40:
                continue
            if evalTotalTime > 40:
                continue
            if execTotalTime > 40:
                continue
            query = params.get("query").strip()
            if not query:
                continue
            is_bl = False
            for bl in HEAVY_BLACKLIST_METRICS:
                if not isinstance(bl, str):
                    continue
                if bl in query:
                    is_bl = True
                    break
            if is_bl:
                continue
            # avoid multi heavy query
            if REDIS_ONE_KEY_PREFIX in query:
                continue
            # \r\n should not in query ,replace it
            if "\r\n" in query:
                query = query.replace("\r\n", "", -1)
            # \n should not in query ,replace it
            if "\n" in query:
                query = query.replace("\n", "", -1)

            # - startwith for grafana network out

            if query.startswith("-"):
                query = query.replace("-", "", 1)
            md5_str = get_str_md5(query.encode("utf-8"))

            record_name = "{}:{}".format(REDIS_ONE_KEY_PREFIX, md5_str)
            record_expr_dict[record_name] = query
            heavy_expr_set.add(query)
            last_time = heavy_expr_dict.get(query)
            this_time = evalTotalTime
            if last_time and last_time > this_time:
                this_time = last_time

            heavy_expr_dict[query] = this_time
    logging.info("log_file:{} get :{} heavy expr".format(log_f, len(record_expr_dict)))
    return record_expr_dict


# 解析一个日志文件
def run_log_parse_local_test(log_path):
    res = parse_log_file(log_path)
    print(res)


def mset_record_to_redis(res_dic):
    if not res_dic:
        logging.fatal("record_expr_list empty")
    rc = redis_conn()
    if not rc:
        logging.fatal("failed to connect to redis-server")
    mset_res = rc.mset(res_dic)
    logging.info("mset_res:{} len:{}".format(str(mset_res), format(len(res_dic))))
    sadd_res = rc.sadd(REDIS_SET_KEY, *res_dic.keys())
    logging.info("sadd_res:{}".format(str(sadd_res)))
    smems = rc.smembers(REDIS_SET_KEY)
    logging.info("smember_res_len:{}".format(len(smems)))


def write_record_yaml_file(record_expr_list):
    '''
    data = {
        "groups": [
            {
                "name": "example",
                "rules": [
                    {
                        "record": "nyy_record_test_a",
                        "expr": "sum(kafka_log_log_size{project=~"metis-main1-sg2"}) by (topic)"
                    },
                ],
            },
        ]

    }
    '''
    data = {
        "groups": [
            {
                "name": "heavy_expr_record",
                "rules": record_expr_list,
            },
        ]

    }
    file_name = "{}/record_{}_{}.yml".format(PROME_RECORD_FILE, len(record_expr_list), now_date_str())
    with open(file_name, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    if not os.path.isfile("./promtool"):
        logging.error("promtool not exist skip rule check ")
        return []

    cmd = "./promtool check rules {}".format(file_name)
    r = os.popen(cmd)
    out = r.read()
    r.close()

    record_name_re = re.compile('.*?\"(%s:.*?)\".*?' % REDIS_ONE_KEY_PREFIX)
    invalid_keys = []
    for line in out.strip().split("\n"):

        record_name = re.findall(record_name_re, line)
        logging.info("[record_name:{}]".format(record_name))
        if len(record_name) == 1:
            invalid_keys.append(record_name[0])
    return invalid_keys


def recovery_concurrent_log_parse(res_dic):
    if not res_dic:
        logging.fatal("get empty result exit ....")
    # print(res_dic)
    # return

    consul_client = Consul(CONSUL_HOST, CONSUL_PORT)
    if not consul_client:
        logging.fatal("connect_to_consul_error")

    # purge consul
    purge_consul_res = consul_client.delete_key(key=CONSUL_RECORD_KEY_PREFIX)
    logging.info("[purge consul] res:{}".format(str(purge_consul_res)))
    # purge redis
    rc = redis_conn()
    if not rc:
        logging.fatal("failed to connect to redis-server")

    rc_delete_res = batch_delete_redis_key(rc, "hke:heavy_expr*")
    logging.info("[purge redis heavy_key] res:{}".format(str(rc_delete_res)))
    rc_delete_res = rc.delete("hke:heavy_query_set")
    logging.info("[purge redis heavy_query_set] res:{}".format(str(rc_delete_res)))

    record_expr_list = []
    for k in sorted(res_dic.keys()):
        record_expr_list.append({"record": k, "expr": res_dic.get(k)})
    logging.info("get_all_record_heavy_query:{} ".format(len(record_expr_list)))

    # write to local prome record yml
    write_record_yaml_file(record_expr_list)

    # write to consul

    new_record_expr_list = []
    for index, data in enumerate(record_expr_list):
        new_record_expr_list.append((index, data))

    consul_w_res = consul_client.txn_mset(new_record_expr_list)
    if not consul_w_res:
        logging.fatal("write_to_consul_error")

    # write to redis
    mset_record_to_redis(res_dic)


def query_range_judge_heavy(host, expr, record):
    '''

    :param host:
    :param expr:
    调用举例: 获取group=ugc的project

    query_range(inf,
            'avg(100 - (avg by (instance,name) (rate(node_cpu_seconds_total{region=~"ap-southeast-3",account=~"HW-SHAREit",group=~"UGC",project=~"cassandra-client", mode="idle"}[5m])) * 100))')


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
    q_start = time.time()
    start = end - 60 * 60

    G_PARMS = {
        "query": expr,
        "start": start,
        "end": end,
        "step": 30
    }
    res = requests.get(uri, G_PARMS)
    data = res.json()
    status = data.get("status")
    if status != "success":
        return (expr, record, False)

    res = data.get("data").get("result")
    if not res:
        return (expr, record, False)
    if len(res) == 0:
        return (expr, record, False)
    took = time.time() - q_start
    logging.info("key:{} expr:{} time_took:{}".format(
        record,
        expr,
        took
    ))
    if took > 3.0:
        return (expr, record, True)
    return (expr, record, False)


def concurrent_log_parse(log_dir):
    # 步骤1 解析日志
    t_num = 500
    pool = ThreadPool(t_num)

    log_file_s = glob.glob("{}/*.log".format(log_dir))

    results = pool.map(parse_log_file, log_file_s)

    pool.close()
    pool.join()
    res_dic = {}
    for x in results:
        res_dic.update(x)
    logging.info("[before_heavy_query_check_num:{}]".format(len(res_dic)))
    # 1 end

    # 步骤2 拿解析结果去查询一下，做double-check，可以禁止
    # pool = ThreadPool(t_num)
    #
    # parms = []
    # for k, v in res_dic.items():
    #     expr = res_dic
    #     record = k
    #     parms.append([CHECK_HEAVY_QUERY_API, expr, record])
    # results = pool.starmap(query_range_judge_heavy, parms)
    #
    # pool.close()
    # pool.join()
    #
    # res_dic = {}
    # for x in results:
    #     expr, record, real_heavy = x[0], x[1], x[2]
    #     if real_heavy:
    #         res_dic[record] = expr
    # logging.info("[after_heavy_query_check_num:{}]".format(len(res_dic)))
    # 2 end

    if not res_dic:
        logging.fatal("get empty result exit ....")

    #  步骤3 增量更新consul数据
    consul_client = Consul(CONSUL_HOST, CONSUL_PORT)
    if not consul_client:
        logging.fatal("connect_to_consul_error")

    ## get pre data from consul
    pre_dic = consul_client.get_list(key=CONSUL_RECORD_KEY_PREFIX)
    old_len = len(pre_dic) + 1
    # res_dic.update(pre_dic)
    ## 增量更新
    old_key_set = set(pre_dic.keys())
    this_key_set = set(res_dic.keys())
    ## 更新的keys
    new_dic = {}
    today_all_dic = {}
    new_key_set = this_key_set - old_key_set
    logging.info("new_key_set:{} ".format(len(new_key_set)))
    for k in new_key_set:
        new_dic[k] = res_dic[k]

    # 构造record 记录
    record_list_new = []
    for k in sorted(new_dic.keys()):
        one_expr_list = {"record": k, "expr": new_dic.get(k)}

        record_list_new.append(one_expr_list)

    # 写入本地record文件检查rules
    invalid_keys = write_record_yaml_file(record_list_new)
    logging.info("invalid_keys: num {}  details:{}".format(len(invalid_keys), str(invalid_keys)))
    for del_key in invalid_keys:
        new_dic.pop(del_key)
    f_record_list_new = []
    for k in sorted(new_dic.keys()):
        one_expr_list = {"record": k, "expr": new_dic.get(k)}

        f_record_list_new.append(one_expr_list)

    today_all_dic.update(pre_dic)
    today_all_dic.update(new_dic)
    local_record_expr_list = []

    for k in sorted(today_all_dic.keys()):
        local_record_expr_list.append({"record": k, "expr": today_all_dic.get(k)})
    logging.info("get_all_record_heavy_query:{} ".format(len(local_record_expr_list)))

    # 写入本地yaml
    write_record_yaml_file(local_record_expr_list)

    # 写入consul中
    new_record_expr_list = []
    # 给record记录添加索引，为confd分片做准备
    for index, data in enumerate(f_record_list_new):
        new_record_expr_list.append((index + old_len, data))
    if new_record_expr_list:
        consul_w_res = consul_client.txn_mset(new_record_expr_list)
        if not consul_w_res:
            logging.fatal("write_to_consul_error")
    else:
        logging.info("zero_new_heavy_record:{}")

    # 写入redis中
    mset_record_to_redis(today_all_dic)


def run():
    '''
    1.all prome query_log need to be scpped  here
    2.parse log
    3.txn_mput to consul
    4.merge result and meset to redis
    5.generate record yaml file

    :return:
    '''
    concurrent_log_parse(PROME_QUERY_LOG_DIR)


yaml_path = G_VAR_YAML

config = load_base_config(yaml_path)
# path
HEAVY_QUERY_THREHOLD = config.get("prome_query_log").get("heavy_query_threhold")
PROME_QUERY_LOG_DIR = config.get("prome_query_log").get("local_work_dir")
PROME_RECORD_FILE = config.get("prome_query_log").get("local_record_yml_dir")
CHECK_HEAVY_QUERY_API = config.get("prome_query_log").get("check_heavy_query_api")
# redis
ONLINE_REDIS_HOST = config.get("redis").get("host")
ONLINE_REDIS_PORT = int(config.get("redis").get("port"))
REDIS_SET_KEY = config.get("redis").get("redis_set_key")
REDIS_ONE_KEY_PREFIX = config.get("redis").get("redis_one_key_prefix")
# consul
CONSUL_RECORD_KEY_PREFIX = config.get("consul").get("consul_record_key_prefix")
CONSUL_HOST = config.get("consul").get("host")
CONSUL_PORT = config.get("consul").get("port")
# heavy

HEAVY_BLACKLIST_METRICS = config.get("heavy_blacklist_metrics")

# print(HEAVY_BLACKLIST_METRICS)

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == "run_log_parse_local_test":
        run_log_parse_local_test(sys.argv[2])
        sys.exit(0)

    try:
        run()
    except Exception as e:
        logging.error("got_error:{}".format(e))
