#!/usr/bin/env bash


last_file=`ls /App/tgzs/conf_dir/prome_heavy_expr_parse/local_record_yml/*yml -rt |tail -1`
metrics=$1
grep $1 ${last_file} ${last_file} -B 1 |grep "record: hke:heavy_expr" |sort |awk -F ":" '{print $NF}' |sort |uniq >  to_del_record_key_file
wc -l to_del_record_key_file

python3 consul_delete.py
