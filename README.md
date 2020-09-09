![image](https://github.com/ning1875/pre_query/blob/master/images/arch.jpg)
![image](https://github.com/ning1875/pre_query/blob/master/images/heavy_query_diff.png)

# heavy_query原因总结 
## 资源原因
- 因为tsdb都有压缩算法对datapoint压缩，比如dod 和xor
- 那么当查询时数据必然涉及到解压放大的问题
- 比如压缩正常一个datapoint大小为16byte
- 一个heavy_query加载1万个series，查询时间24小时，30秒一个点来算，所需要的内存大小为 439MB，所以同时多个heavy_query会将prometheus内存打爆，prometheus也加了上面一堆参数去限制
- 当然除了上面说的queryPreparation过程外，查询时还涉及sort和eval等也需要耗时

## prometheus原生不支持downsample
- 还有个原因是prometheus原生不支持downsample，所以无论grafana上面的step随时间如何变化，涉及到到查询都是将指定的block解压再按step切割
- 所以查询时间跨度大对应消耗的cpu和内存就会报增，同时原始点的存储也浪费了，因为grafana的step会随时间跨度变大变大
## 实时查询/聚合 VS 预查询/聚合
prometheus的query都是实时查询的/聚合
**实时查询的优点很明显**
- 查询/聚合条件随意组合，比如 rate后再sum然后再叠加一个histogram_quantile

**实时查询的缺点也很明显**
- 那就是慢，或者说资源消耗大
**实时查询的优缺点反过来就是预查询/聚合的**
一个预聚合的例子请看我写的falcon组件 [监控聚合器系列之: open-falcon新聚合器polymetric](https://segmentfault.com/a/1190000023092934)
- 所有的聚合方法提前定义好，并定时被计算出结果
- 查询时不涉及任何的聚合，直接查询结果
- 比如实时聚合需要每次加载10万个series，预聚合则只需要查询几个结果集
**那么问题来了prometheus有没有预查询/聚合呢**
答案是有的
## prometheus的预查询/聚合
[prometheus record](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/)

Recording rules allow you to precompute frequently needed or computationally expensive expressions and save their result as a new set of time series. Querying the precomputed result will then often be much faster than executing the original expression every time it is needed. This is especially useful for dashboards, which need to query the same expression repeatedly every time they refresh.

# 本项目说明
## 解决方案说明  
- heavy_query对用户侧表现为查询速度慢  
- 在服务端会导致资源占用过多甚至打挂后端存储  
- 查询如果命中heavy_query策略(目前为查询返回时间超过2秒)则会被替换为预先计算好的轻量查询结果返回,两种方式查询的结果一致  
- 未命中的查询按原始查询返回  
- 替换后的metrics_name 会变成 `hke:heavy_expr:xxxx` 字样,而对应的tag不变。对于大分部panel中已经设置了曲线的Legend,所以展示没有区别  
- 现在每晚23:30增量更新heavy_query策略。对于大部分设定好的dashboard没有影响(因为已经存量heavy_query已经跑7天以上了),对于新增策略会从策略生效后开始展示数据,对于查询高峰的白天来说至少保证有10+小时的数据

## 代码架构说明
- parse组件根据prometheus的query log分析heavy_query记录
- 把记录算哈希后增量写入consul，和redis集群中
- prometheus 根据confd拉取属于自己分片的consul数据生成record.yml
- 根据record做预查询聚合写入tsdb
- query前面的lua会将grafana传过来的查询expr算哈希
- 和redis中的记录匹配，匹配中说明这条是heavy_query
- 那么替换其expr到后端查询


## 使用指南

### prometheus 和confd组件
```
# 安装prometheus 和confd
# 将confd下的配置文件放置好，启动服务
# prometheus开启query_log 

global:
  query_log_file: /App/logs/prometheus_query.log
```



### openresty和lua组件
```
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

```


### parse和ansible组件 在python3.6+中运行
```
# 安装依赖
pip3 install -r  requirements.txt

# 修改config.yaml中各个配置
# 准备真实prometheus地址写入all_prome_query
# 运行添加crontab 每晚11:30定时运行一次即可
ansible-playbook -i all_prome_query  prome_heavy_expr_parse.yaml
```


## 运维指南
```
# 查看redis中的heavy_query记录
redis-cli -h $redis_host   keys hke:heavy_expr*
# 查看consul中的heavy_query记录
curl http://$consul_addr:8500/v1/kv/prometheus/record?recurse= |python -m json.tool
# 根据一个heavy_record文件恢复记录
python3 recovery_by_local_yaml.py local_record_yml/record_to_keep.yml
# 根据一个metric_name前缀删除record记录
bash -x recovery_heavy_metrics.sh  $metric_name
```
