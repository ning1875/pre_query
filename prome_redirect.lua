function get_str_md5(input_s)
    local resty_md5 = require "resty.md5"
    local md5 = resty_md5:new()
    if not md5 then
        ngx.log(ngx.ERR, "failed to create md5 object")
        return
    end

    local ok = md5:update(input_s)
    if not ok then
        ngx.log(ngx.ERR, "failed to add data")
        return
    end
    local digest = md5:final()

    local str = require "resty.string"
    local md5_str = str.to_hex(digest)
    return md5_str
end

function redis_get(key)
    -- start of redis

    local redis = require "resty.redis"
    local red = redis:new()
    --red:set_timeouts(1000, 1000, 1000)
    local ok, conn_err = red:connect("localhost", 6379)
    if not ok then
        ngx.log(ngx.ERR, "[redis]failed to connect redis server:", conn_err)
        return false
    end

    local res, get_err = red:get(key)
    if get_err then
        ngx.log(ngx.ERR, "[redis]failed to get value by key: ", key, "err:", get_err)
        return false
    end

    red:set_keepalive(30000, 1000)
    if res ~= ngx.null then
        ngx.log(ngx.INFO, "[redis]success  get value by key: ", key, "value: ", res)
        return true
    else
        return false
    end

    -- end of  redis
end

function replace_work()
    --Nginx服务器中使用lua获取get或post参数

    local request_method = ngx.var.request_method;
    local args = {}
    --获取参数的值

    if "GET" == request_method then
        args = ngx.req.get_uri_args();
    elseif "POST" == request_method then
        ngx.req.read_body();
        args = ngx.req.get_post_args();
    end

    local q_query = args["query"];
    local q_start = args["start"];
    local q_end = args["end"];
    local q_step = args["step"];

    local md5_str = get_str_md5(q_query)

    if md5_str == null then
        return
    end
    local redis_query_key = "hke:heavy_expr:" .. md5_str
    --ngx.log(ngx.ERR, "redis_query_key: ",redis_query_key)
    local redis_get_res = redis_get(redis_query_key)
    if redis_get_res == true then
        q_query = redis_query_key
    end

    local new_args = {}
    new_args["query"] = q_query
    new_args["start"] = q_start
    new_args["end"] = q_end
    new_args["step"] = q_step

    ngx.req.set_uri_args(new_args)
    --ngx.req.set_uri_args("end=" .. q_end)
    --local arg = ngx.req.get_uri_args()
    --for k, v in pairs(arg) do
    --    ngx.say("[GET ] key:", k, " v:", v)
    --end

end

return replace_work();