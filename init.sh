#!/usr/bin/env bash

# 安装指南
# parse组件 在python3.6+中运行
#1.安装依赖
# pip3 install -r  requirements.txt

#2. 修改config.yaml中各个配置
#3. 准备真实prometheus地址写入all_prome_query
#4. 运行添加crontab 每晚11:30定时运行一次即可
ansible-playbook -i all_prome_query  prome_heavy_expr_parse.yaml


# prometheus 和confd组件
# 1.安装prometheus 和confd
# 将confd下的配置文件放置好，启动服务
# prometheus开启query_log
```
global:
  query_log_file: /App/logs/prometheus_query.log
```

# openresty组件
#1. 安装openresty ，准备lua环境
yum install yum-utils -y
yum-config-manager --add-repo https://openresty.org/package/centos/openresty.repo
yum install openresty openresty-resty -y

#2.
# 修改lua文件中的redis地址为你自己的
# 修改ngx_prome_redirect.conf文件中 真实real_prometheus后端,使用前请修改

mkdir -pv /usr/local/openresty/nginx/conf/conf.d/
mkdir -pv /usr/local/openresty/nginx/lua_files/

#3.
# 将nginx配置和lua文件放到指定目录
/bin/cp -f  ngx_prome_redirect.conf /usr/local/openresty/nginx/conf/conf.d/
/bin/cp -f  nginx.conf /usr/local/openresty/nginx/conf/
/bin/cp -f prome_redirect.lua /usr/local/openresty/nginx/lua_files/


#4.
# 启动openresty
systemctl enable openresty
systemctl start openresty

#5.
# 修改grafana数据源，将原来的指向真实prometheus地址改为指向openresty的9992端口


# 运维操作
# 查看redis中的heavy_query记录
redis-cli -h $redis_host   keys hke:heavy_expr*
# 查看consul中的heavy_query记录
curl http://$consul_addr:8500/v1/kv/prometheus/record?recurse= |python -m json.tool
# 根据一个heavy_record文件恢复记录
python3 recovery_by_local_yaml.py local_record_yml/record_to_keep.yml
# 根据一个metric_name前缀删除record记录
bash -x recovery_heavy_metrics.sh  $metric_name






