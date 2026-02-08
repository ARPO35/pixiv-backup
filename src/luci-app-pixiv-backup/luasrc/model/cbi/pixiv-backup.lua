local fs = require("nixio.fs")
local sys = require("luci.sys")
local uci = require("luci.model.uci").cursor()
local jsonc = require("luci.jsonc")
local util = require("luci.util")
local http = require("luci.http")
local dispatcher = require("luci.dispatcher")

local function _norm(v)
    local s = tostring(v or "-")
    s = s:gsub("[\r\n]", " ")
    s = s:gsub("%s+", " ")
    if s == "" then
        s = "-"
    end
    return s
end

local function write_luci_audit(source, action, status, detail)
    local output_dir = uci:get("pixiv-backup", "settings", "output_dir") or "/mnt/sda1/pixiv-backup"
    local log_dir = output_dir .. "/data/logs"
    local log_file = log_dir .. "/pixiv-backup-" .. os.date("%Y%m%d") .. ".log"
    local ip = _norm(http.getenv("REMOTE_ADDR"))
    local ua = _norm(http.getenv("HTTP_USER_AGENT"))

    local line = string.format(
        "%s - pixiv-backup.audit - INFO - event=luci_action source=%s action=%s status=%s ip=%s ua=%s detail=%s\n",
        os.date("%Y-%m-%d %H:%M:%S"),
        _norm(source),
        _norm(action),
        _norm(status),
        ip,
        ua,
        _norm(detail)
    )
    fs.mkdirr(log_dir)
    local f = io.open(log_file, "a")
    if f then
        f:write(line)
        f:close()
    end

    local syslog_msg = string.format(
        "event=luci_action source=%s action=%s status=%s ip=%s detail=%s",
        _norm(source), _norm(action), _norm(status), ip, _norm(detail)
    )
    sys.call("logger -t pixiv-backup-audit " .. util.shellquote(syslog_msg))
end

-- Ensure the named section exists to avoid nsection.htm errors
if not uci:get("pixiv-backup", "settings") then
    uci:section("pixiv-backup", "main", "settings", {})
    uci:commit("pixiv-backup")
end

m = Map("pixiv-backup", "Pixiv备份设置", "配置Pixiv收藏和关注列表的自动备份服务")
m.on_after_commit = function(self)
    local enabled_value = uci:get("pixiv-backup", "settings", "enabled")
    if enabled_value == "1" then
        local rc = sys.call("/etc/init.d/pixiv-backup enable >/dev/null 2>&1")
        write_luci_audit("cbi", "config_commit_enable", rc == 0 and "ok" or "error", "enabled=1")
    else
        local rc = sys.call("/etc/init.d/pixiv-backup disable >/dev/null 2>&1")
        write_luci_audit("cbi", "config_commit_disable", rc == 0 and "ok" or "error", "enabled=0")
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

timeout = s:option(Value, "timeout", "请求超时", "网络请求超时时间（秒）")
timeout.default = "30"
timeout.datatype = "uinteger"

sync_interval_minutes = s:option(Value, "sync_interval_minutes", "巡检间隔（分钟）", "守护进程每隔多少分钟检查一次新作品")
sync_interval_minutes.default = "360"
sync_interval_minutes.datatype = "uinteger"

cooldown_after_limit_minutes = s:option(Value, "cooldown_after_limit_minutes", "达到下载上限冷却（分钟）", "单次同步达到最大下载数量后进入冷却")
cooldown_after_limit_minutes.default = "60"
cooldown_after_limit_minutes.datatype = "uinteger"

cooldown_after_error_minutes = s:option(Value, "cooldown_after_error_minutes", "限速/错误冷却（分钟）", "遇到 403/429/502 等限速错误后进入冷却")
cooldown_after_error_minutes.default = "180"
cooldown_after_error_minutes.datatype = "uinteger"

interval_jitter_ms = s:option(Value, "interval_jitter_ms", "下载间隔随机偏移（毫秒）", "每张图片下载间隔额外增加随机偏移，范围 [0, 该值]，仅增加不减少")
interval_jitter_ms.default = "1000"
interval_jitter_ms.datatype = "uinteger"

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
    local data = read_runtime_status()
    local err = data.last_error
    if not err or err == "" then
        return "<pre>无</pre>"
    end
    return "<pre>" .. util.pcdata(err) .. "</pre>"
end

local live_panel = status_section:option(DummyValue, "_live_panel", "实时状态（1秒自动同步）")
live_panel.rawhtml = true
live_panel.cfgvalue = function(self, section)
    local status_url = dispatcher.build_url("admin", "services", "pixiv-backup", "status")
    return string.format([[
<div class="cbi-value">
  <div class="cbi-value-field">
    <div>服务状态: <span id="pb-live-service-status">-</span></div>
    <div>当前任务状态: <span id="pb-live-runtime-state">-</span></div>
    <div>本轮进度: <span id="pb-live-runtime-progress">-</span></div>
    <div>冷却信息: <span id="pb-live-runtime-cooldown">-</span></div>
    <div>总共已处理: <span id="pb-live-total-processed">0</span></div>
    <div>队列汇总: <span id="pb-live-queue-summary">total=0 pending=0 running=0 failed=0 permanent_failed=0 done=0</span></div>
    <div>最近错误: <span id="pb-live-last-error">无</span></div>
  </div>
</div>
<script>
(function() {
  if (window.__pixivBackupLiveBound) return;
  window.__pixivBackupLiveBound = true;
  var statusUrl = '%s';

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = (value === undefined || value === null || value === '') ? '-' : String(value);
  }

  function updateStatus() {
    fetch(statusUrl, { cache: 'no-store' })
      .then(function(resp) { return resp.json(); })
      .then(function(data) {
        var runtime = data.runtime || {};
        var stats = data.stats || {};
        var queue = data.queue_summary || {};
        setText('pb-live-service-status', data.service_status || '-');
        setText('pb-live-runtime-state', runtime.phase ? (runtime.state + '/' + runtime.phase) : (runtime.state || '-'));
        setText('pb-live-runtime-progress', '已处理=' + (runtime.processed_total || 0) + ' 成功=' + (runtime.success || 0) + ' 跳过=' + (runtime.skipped || 0) + ' 失败=' + (runtime.failed || 0));
        if (runtime.state === 'cooldown') {
          setText('pb-live-runtime-cooldown', '原因=' + (runtime.cooldown_reason || '-') + ' 下次=' + (runtime.next_run_at || '-'));
        } else {
          setText('pb-live-runtime-cooldown', '无');
        }
        setText('pb-live-total-processed', stats.total_processed_all || 0);
        setText('pb-live-queue-summary', 'total=' + (queue.total || 0) + ' pending=' + (queue.pending || 0) + ' running=' + (queue.running || 0) + ' failed=' + (queue.failed || 0) + ' permanent_failed=' + (queue.permanent_failed || 0) + ' done=' + (queue.done || 0));
        setText('pb-live-last-error', runtime.last_error || '无');
      })
      .catch(function() {
        setText('pb-live-runtime-state', 'status接口读取失败');
      });
  }

  updateStatus();
  setInterval(updateStatus, 1000);
})();
</script>
]], status_url)
end

local start_btn = status_section:option(Button, "_start", "立即开始备份")
start_btn.inputtitle = "跳过冷却并立即扫描"
start_btn.inputstyle = "apply"
start_btn.write = function(self, section)
    local output_dir = uci:get("pixiv-backup", "settings", "output_dir") or "/mnt/sda1/pixiv-backup"
    local rc = sys.call("pixiv-backup trigger >/tmp/pixiv-backup-start.log 2>&1")
    local result = fs.readfile("/tmp/pixiv-backup-start.log") or ""
    write_luci_audit("cbi", "trigger", rc == 0 and "ok" or "error", result ~= "" and result or "no_output")
end

local stop_btn = status_section:option(Button, "_stop", "停止服务")
stop_btn.inputtitle = "停止备份"
stop_btn.inputstyle = "reset"
stop_btn.write = function(self, section)
    local rc = sys.call("pixiv-backup stop >/tmp/pixiv-backup-stop.log 2>&1")
    local result = fs.readfile("/tmp/pixiv-backup-stop.log") or ""
    write_luci_audit("cbi", "stop", rc == 0 and "ok" or "error", result ~= "" and result or "no_output")
end

return m
