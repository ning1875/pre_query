import datetime
import hashlib

import yaml


def now_date_str():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def get_str_md5(input_str):
    m = hashlib.md5()
    m.update(input_str)
    return m.hexdigest()


def load_base_config(yaml_path):
    with open(yaml_path) as f:
        config = yaml.load(f)
    return config
