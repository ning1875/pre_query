import re

prefix = "hke:heavy_expr"

record_name_re = re.compile('.*?\"(%s:.*?)\".*?' % prefix)
s = ' local_record_yml_dir/record_28_2021-09-13_14-41-16.yml: 80:11: group "heavy_expr_record", rule 27, "hke:heavy_expr:ed28d1000288d2c806827acfc2cfb48b": could not parse expression: 1:90: parse error: unexpected identifier "ormax_over_time"'
record_name = re.findall(record_name_re, s)
print(record_name)
