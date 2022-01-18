# k8s教程说明
- [k8s底层原理和源码讲解之精华篇](https://ke.qq.com/course/4093533)
- [k8s底层原理和源码讲解之进阶篇](https://ke.qq.com/course/4236389)

# prometheus全组件的教程

- [01_prometheus全组件配置使用、底层原理解析、高可用实战](https://ke.qq.com/course/3549215?tuin=361e95b0)
- [02_prometheus-thanos使用和源码解读](https://ke.qq.com/course/3883439?tuin=361e95b0)
- [03_kube-prometheus和prometheus-operator实战和原理介绍](https://ke.qq.com/course/3912017?tuin=361e95b0)
- [04_prometheus源码讲解和二次开发](https://ke.qq.com/course/4236995?tuin=361e95b0)


# 关于白嫖和付费
- 白嫖当然没关系，我已经贡献了很多文章和开源项目，当然还有免费的视频
- 但是客观的讲，如果你能力超强是可以一直白嫖的，可以看源码。什么问题都可以解决
- 看似免费的资料很多，但大部分都是边角料，核心的东西不会免费，更不会有大神给你答疑
- thanos和kube-prometheus如果你对prometheus源码把控很好的话，再加上k8s知识的话就觉得不难了


# 架构图
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

[安装部署](./部署.md)
