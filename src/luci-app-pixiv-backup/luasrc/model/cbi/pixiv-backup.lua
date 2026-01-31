m = Map("pixiv-backup", "Pixiv备份设置", "配置Pixiv收藏和关注列表的自动备份服务")

-- 状态显示部分
s = m:section(TypedSection, "main", "服务状态")
s.anonymous = true

status = s:option(DummyValue, "_status", "当前状态")
status.template = "cbi/dvalue"
status.value = function()
    local sys = require("luci.sys")
    local pid = sys.exec("pgrep -f 'pixiv-backup'")
    if pid and pid ~= "" then
        return "<span style='color: green'>● 运行中</span>"
    else
        return "<span style='color: red'>● 已停止</span>"
    end
end

stats = s:option(DummyValue, "_stats", "统计信息")
stats.template = "cbi/dvalue"
stats.value = function()
    local sys = require("luci.sys")
    local db_path = "/mnt/sda1/pixiv-backup/data/pixiv.db"
    local count = "0"
    local storage = "0MB"
    
    if nixio.fs.access(db_path) then
        count = sys.exec("sqlite3 '" .. db_path .. "' 'SELECT COUNT(*) FROM illusts;' 2>/dev/null") or "0"
        storage = sys.exec("du -sh /mnt/sda1/pixiv-backup/img/ 2>/dev/null | cut -f1") or "0MB"
    end
    
    return string.format("已下载: %s 作品 | 存储使用: %s", count:gsub("%s+", ""), storage:gsub("%s+", ""))
end

-- 基础设置部分
s = m:section(TypedSection, "main", "基础设置")
s.anonymous = true

enabled = s:option(Flag, "enabled", "启用服务", "启用自动备份服务")
enabled.default = 0

user_id = s:option(Value, "user_id", "Pixiv用户ID", "需要备份的Pixiv用户ID")
user_id.datatype = "uinteger"
user_id.optional = false

refresh_token = s:option(Value, "refresh_token", "Refresh Token", "Pixiv API的refresh token")
refresh_token.password = true
refresh_token.optional = false

output_dir = s:option(Value, "output_dir", "输出目录", "图片和元数据的存储目录")
output_dir.default = "/mnt/sda1/pixiv-backup"
output_dir.datatype = "directory"
output_dir.optional = false

-- 下载设置部分
s = m:section(TypedSection, "download", "下载设置")
s.anonymous = true
s.addremove = false

download_mode = s:option(ListValue, "mode", "下载模式", "选择要下载的内容类型")
download_mode:value("bookmarks", "仅收藏")
download_mode:value("following", "仅关注用户作品")
download_mode:value("both", "收藏和关注用户作品")
download_mode.default = "bookmarks"

restrict = s:option(ListValue, "restrict", "内容范围", "选择要下载的内容范围")
restrict:value("public", "公开内容")
restrict:value("private", "私有内容（需要登录）")
restrict.default = "public"

max_downloads = s:option(Value, "max_downloads", "最大下载数量", "单次运行最多下载的作品数量（0表示无限制）")
max_downloads.default = "1000"
max_downloads.datatype = "uinteger"

-- 过滤设置部分
s = m:section(TypedSection, "filter", "过滤设置")
s.anonymous = true
s.addremove = false

min_bookmarks = s:option(Value, "min_bookmarks", "最小收藏数", "只下载收藏数超过此值的作品（0表示不过滤）")
min_bookmarks.default = "0"
min_bookmarks.datatype = "uinteger"

r18_mode = s:option(ListValue, "r18_mode", "R18内容处理", "选择如何处理R18内容")
r18_mode:value("skip", "跳过R18内容")
r18_mode:value("only", "仅下载R18内容")
r18_mode:value("both", "下载所有内容")
r18_mode.default = "skip"

include_tags = s:option(Value, "include_tags", "包含标签", "只下载包含这些标签的作品（逗号分隔，留空表示不过滤）")
include_tags.optional = true

exclude_tags = s:option(Value, "exclude_tags", "排除标签", "跳过包含这些标签的作品（逗号分隔，留空表示不过滤）")
exclude_tags.optional = true

-- 计划任务部分
s = m:section(TypedSection, "schedule", "计划任务")
s.anonymous = true
s.addremove = false

schedule_enabled = s:option(Flag, "enabled", "启用定时任务", "定时自动运行备份")
schedule_enabled.default = 0

schedule_time = s:option(Value, "time", "运行时间", "每天运行的时间（24小时制，HH:MM格式）")
schedule_time.default = "03:00"
schedule_time.datatype = "timehhmm"
schedule_time:depends({enabled = "1"})

-- 网络设置部分
s = m:section(TypedSection, "network", "网络设置")
s.anonymous = true
s.addremove = false

proxy_enabled = s:option(Flag, "proxy_enabled", "启用代理", "使用代理服务器访问Pixiv")
proxy_enabled.default = 0

proxy_url = s:option(Value, "proxy_url", "代理地址", "代理服务器地址（例如：http://127.0.0.1:7890）")
proxy_url:depends({proxy_enabled = "1"})

timeout = s:option(Value, "timeout", "请求超时", "网络请求超时时间（秒）")
timeout.default = "30"
timeout.datatype = "uinteger"

-- 操作按钮部分
s = m:section(NamedSection, "main", "pixiv-backup", "操作")
s.anonymous = true

test_button = s:option(Button, "_test", "测试连接")
test_button.inputtitle = "测试Pixiv API连接"
test_button.inputstyle = "apply"
test_button.write = function()
    local sys = require("luci.sys")
    local result = sys.exec("/usr/share/pixiv-backup/tools/test_connection.py 2>&1")
    m.message = result
end

manual_button = s:option(Button, "_manual", "手动运行")
manual_button.inputtitle = "立即开始备份"
manual_button.inputstyle = "apply"
manual_button.write = function()
    local sys = require("luci.sys")
    local result = sys.exec("/etc/init.d/pixiv-backup start 2>&1")
    m.message = "已开始手动备份：" .. result
end

return m