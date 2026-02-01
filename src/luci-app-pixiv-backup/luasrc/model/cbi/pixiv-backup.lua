local fs = require("nixio.fs")
local sys = require("luci.sys")
local uci = require("luci.model.uci").cursor()

m = Map("pixiv-backup", "Pixiv备份设置", "配置Pixiv收藏和关注列表的自动备份服务")

s = m:section(NamedSection, "settings", "main", "配置", true)
s.anonymous = true
s.addremove = false

-- 基础设置
enabled = s:option(Flag, "enabled", "启用服务", "启用自动备份服务")
enabled.default = "0"

user_id = s:option(Value, "user_id", "Pixiv用户ID", "需要备份的Pixiv用户ID")
user_id.datatype = "uinteger"

refresh_token = s:option(Value, "refresh_token", "Refresh Token", "Pixiv API的refresh token")
refresh_token.password = true

output_dir = s:option(Value, "output_dir", "输出目录", "图片和元数据的存储目录")
output_dir.default = "/mnt/sda1/pixiv-backup"

-- 下载设置
download_mode = s:option(ListValue, "mode", "下载模式", "选择要下载的内容类型")
download_mode:value("bookmarks", "仅收藏")
download_mode:value("following", "仅关注用户作品")
download_mode:value("both", "收藏和关注用户作品")
download_mode.default = "bookmarks"

restrict = s:option(ListValue, "restrict", "内容范围", "选择要下载的内容范围")
restrict:value("public", "公开内容")
restrict:value("private", "私有内容")
restrict.default = "public"

max_downloads = s:option(Value, "max_downloads", "最大下载数量", "单次运行最多下载的作品数量（0表示无限制）")
max_downloads.default = "1000"
max_downloads.datatype = "uinteger"

-- 过滤设置
min_bookmarks = s:option(Value, "min_bookmarks", "最小收藏数", "只下载收藏数超过此值的作品")
min_bookmarks.default = "0"
min_bookmarks.datatype = "uinteger"

r18_mode = s:option(ListValue, "r18_mode", "R18内容处理", "选择如何处理R18内容")
r18_mode:value("skip", "跳过R18内容")
r18_mode:value("only", "仅下载R18内容")
r18_mode:value("both", "下载所有内容")
r18_mode.default = "skip"

include_tags = s:option(Value, "include_tags", "包含标签", "只下载包含这些标签的作品（逗号分隔）")
include_tags.placeholder = "tag1,tag2,tag3"

exclude_tags = s:option(Value, "exclude_tags", "排除标签", "跳过包含这些标签的作品（逗号分隔）")
exclude_tags.placeholder = "tag1,tag2,tag3"

-- 网络设置
proxy_enabled = s:option(Flag, "proxy_enabled", "启用代理", "使用代理服务器访问Pixiv")
proxy_enabled.default = "0"

proxy_url = s:option(Value, "proxy_url", "代理地址", "代理服务器地址")
proxy_url.placeholder = "http://127.0.0.1:7890"
proxy_url:depends("proxy_enabled", "1")

timeout = s:option(Value, "timeout", "请求超时", "网络请求超时时间（秒）")
timeout.default = "30"
timeout.datatype = "uinteger"

-- 计划任务
schedule_enabled = s:option(Flag, "schedule_enabled", "启用定时任务", "定时自动运行备份")
schedule_enabled.default = "0"

schedule_time = s:option(Value, "schedule_time", "运行时间", "每天运行的时间（24小时制）")
schedule_time.default = "03:00"
schedule_time.placeholder = "HH:MM"

-- 状态和操作部分
status_section = m:section(TypedSection, "_dummy", "服务状态")
status_section.anonymous = true
status_section.template = "cbi/nullsection"

local service_status = status_section:option(DummyValue, "_status", "服务状态")
service_status.rawhtml = true
service_status.cfgvalue = function(self, section)
    local pid = sys.exec("pgrep -f 'pixiv-backup' 2>/dev/null")
    if pid and pid ~= "" then
        return '<span style="color: green; font-weight: bold;">● 运行中</span>'
    else
        return '<span style="color: red; font-weight: bold;">● 已停止</span>'
    end
end

local start_btn = status_section:option(Button, "_start", "手动备份")
start_btn.inputtitle = "立即开始备份"
start_btn.inputstyle = "apply"
start_btn.write = function(self, section)
    sys.exec("/etc/init.d/pixiv-backup start &")
end

local stop_btn = status_section:option(Button, "_stop", "停止服务")
stop_btn.inputtitle = "停止备份"
stop_btn.inputstyle = "reset"
stop_btn.write = function(self, section)
    sys.exec("/etc/init.d/pixiv-backup stop")
end

return m