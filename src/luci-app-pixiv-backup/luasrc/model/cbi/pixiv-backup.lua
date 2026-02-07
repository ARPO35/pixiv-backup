local fs = require("nixio.fs")
local sys = require("luci.sys")
local uci = require("luci.model.uci").cursor()
local jsonc = require("luci.jsonc")
local util = require("luci.util")

-- Ensure the named section exists to avoid nsection.htm errors
if not uci:get("pixiv-backup", "settings") then
    uci:section("pixiv-backup", "main", "settings", {})
    uci:commit("pixiv-backup")
end

m = Map("pixiv-backup", "Pixiv备份设置", "配置Pixiv收藏和关注列表的自动备份服务")
m.on_after_commit = function(self)
    local enabled_value = uci:get("pixiv-backup", "settings", "enabled")
    if enabled_value == "1" then
        sys.call("/etc/init.d/pixiv-backup enable >/dev/null 2>&1")
    else
        sys.call("/etc/init.d/pixiv-backup disable >/dev/null 2>&1")
    end
end

s = m:section(NamedSection, "settings", "main", "配置")
s.anonymous = false
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

sync_interval_minutes = s:option(Value, "sync_interval_minutes", "巡检间隔（分钟）", "守护进程每隔多少分钟检查一次新作品")
sync_interval_minutes.default = "360"
sync_interval_minutes.datatype = "uinteger"

cooldown_after_limit_minutes = s:option(Value, "cooldown_after_limit_minutes", "达到下载上限冷却（分钟）", "单次同步达到最大下载数量后进入冷却")
cooldown_after_limit_minutes.default = "60"
cooldown_after_limit_minutes.datatype = "uinteger"

cooldown_after_error_minutes = s:option(Value, "cooldown_after_error_minutes", "限速/错误冷却（分钟）", "遇到 403/429/502 等限速错误后进入冷却")
cooldown_after_error_minutes.default = "180"
cooldown_after_error_minutes.datatype = "uinteger"

high_speed_queue_size = s:option(Value, "high_speed_queue_size", "高速队列数量", "每轮同步开始时优先快速处理的任务数量")
high_speed_queue_size.default = "20"
high_speed_queue_size.datatype = "uinteger"

low_speed_interval_seconds = s:option(Value, "low_speed_interval_seconds", "低速队列间隔（秒）", "超过高速队列后，每个任务之间的等待时间")
low_speed_interval_seconds.default = "1.5"
low_speed_interval_seconds.datatype = "float"

-- 状态和操作部分
status_section = m:section(TypedSection, "_dummy", "服务状态")
status_section.anonymous = true
status_section.template = "cbi/nullsection"

local function read_runtime_status()
    local output_dir = uci:get("pixiv-backup", "settings", "output_dir") or "/mnt/sda1/pixiv-backup"
    local status_file = output_dir .. "/data/status.json"
    if not fs.access(status_file) then
        return {}
    end
    local content = fs.readfile(status_file)
    if not content or content == "" then
        return {}
    end
    local parsed = jsonc.parse(content)
    return parsed or {}
end

local service_status = status_section:option(DummyValue, "_status", "服务状态")
service_status.rawhtml = true
service_status.cfgvalue = function(self, section)
    if sys.call("/etc/init.d/pixiv-backup running >/dev/null 2>&1") == 0 then
        return '<span style="color: green; font-weight: bold;">● 运行中</span>'
    else
        return '<span style="color: red; font-weight: bold;">● 已停止</span>'
    end
end

local runtime_state = status_section:option(DummyValue, "_runtime_state", "当前任务状态")
runtime_state.cfgvalue = function(self, section)
    local data = read_runtime_status()
    return data.state or "unknown"
end

local runtime_progress = status_section:option(DummyValue, "_runtime_progress", "本轮进度")
runtime_progress.cfgvalue = function(self, section)
    local data = read_runtime_status()
    local total = tonumber(data.processed_total or 0) or 0
    local success = tonumber(data.success or 0) or 0
    local skipped = tonumber(data.skipped or 0) or 0
    local failed = tonumber(data.failed or 0) or 0
    return string.format("已处理: %d, 成功: %d, 跳过: %d, 失败: %d", total, success, skipped, failed)
end

local runtime_cooldown = status_section:option(DummyValue, "_runtime_cooldown", "冷却信息")
runtime_cooldown.cfgvalue = function(self, section)
    local data = read_runtime_status()
    if data.state == "cooldown" then
        local reason = data.cooldown_reason or "unknown"
        local next_run_at = data.next_run_at or "-"
        return string.format("原因: %s, 下次巡检: %s", reason, next_run_at)
    end
    return "无"
end

local runtime_errors = status_section:option(DummyValue, "_runtime_errors", "最近错误")
runtime_errors.rawhtml = true
runtime_errors.cfgvalue = function(self, section)
    local output_dir = uci:get("pixiv-backup", "settings", "output_dir") or "/mnt/sda1/pixiv-backup"
    local latest_log = sys.exec("ls -t '" .. output_dir .. "/data/logs/'pixiv-backup-*.log 2>/dev/null | head -n 1")
    latest_log = latest_log and latest_log:gsub("%s+$", "")
    if not latest_log or latest_log == "" then
        return "<pre>暂无错误日志</pre>"
    end
    local err_lines = sys.exec("grep -E 'ERROR|Traceback|Exception|429|403|502|503|504|rate limit|too many requests' '" .. latest_log .. "' 2>/dev/null | tail -n 5")
    if not err_lines or err_lines == "" then
        return "<pre>暂无错误日志</pre>"
    end
    return "<pre>" .. util.pcdata(err_lines) .. "</pre>"
end

local start_btn = status_section:option(Button, "_start", "手动备份")
start_btn.inputtitle = "立即开始备份"
start_btn.inputstyle = "apply"
start_btn.write = function(self, section)
    sys.exec("/etc/init.d/pixiv-backup restart >/tmp/pixiv-backup-start.log 2>&1")
end

local stop_btn = status_section:option(Button, "_stop", "停止服务")
stop_btn.inputtitle = "停止备份"
stop_btn.inputstyle = "reset"
stop_btn.write = function(self, section)
    sys.exec("/etc/init.d/pixiv-backup stop >/tmp/pixiv-backup-stop.log 2>&1")
end

return m
