module("luci.controller.pixiv-backup", package.seeall)

local fs = require("nixio.fs")
local sys = require("luci.sys")
local util = require("luci.util")
local http = require("luci.http")

local function _norm(v)
    local s = tostring(v or "-")
    s = s:gsub("[\r\n]", " ")
    s = s:gsub("%s+", " ")
    if s == "" then
        s = "-"
    end
    return s
end

local function write_luci_audit(output_dir, source, action, status, detail)
    local log_dir = (output_dir or "/mnt/sda1/pixiv-backup") .. "/data/logs"
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

function index()
    entry({"admin", "services", "pixiv-backup"}, cbi("pixiv-backup"), _("Pixiv备份"), 60).dependent = false
    entry({"admin", "services", "pixiv-backup", "status"}, call("action_status")).leaf = true
    entry({"admin", "services", "pixiv-backup", "logs"}, call("action_logs")).leaf = true
    entry({"admin", "services", "pixiv-backup", "start"}, call("action_start")).leaf = true
    entry({"admin", "services", "pixiv-backup", "stop"}, call("action_stop")).leaf = true
end

function action_status()
    local uci = require("luci.model.uci").cursor()
    
    local result = {
        service_status = "stopped",
        config_status = "unconfigured",
        last_run = nil,
        runtime = {},
        recent_errors = {},
        stats = {
            total_downloaded = 0,
            last_24h = 0,
            storage_used = "0MB"
        }
    }
    
    -- 检查服务状态
    if sys.call("/etc/init.d/pixiv-backup running >/dev/null 2>&1") == 0 then
        result.service_status = "running"
    end
    
    -- 检查配置
    local main = uci:get_all("pixiv-backup", "settings")
    if main and main.enabled == "1" and main.user_id and main.user_id ~= "" and main.refresh_token and main.refresh_token ~= "" then
        result.config_status = "configured"
    end
    
    -- 获取输出目录
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    write_luci_audit(output_dir, "controller", "status", "ok", "query_status")
    
    -- 获取统计数据
    local db_path = output_dir .. "/data/pixiv.db"
    if fs.access(db_path) then
        local count = sys.exec("sqlite3 '" .. db_path .. "' 'SELECT COUNT(*) FROM illusts;' 2>/dev/null")
        if count and count ~= "" then
            result.stats.total_downloaded = tonumber(count:gsub("%s+", "")) or 0
        end
        
        -- 计算存储使用量
        local du = sys.exec("du -sh '" .. output_dir .. "/img/' 2>/dev/null | cut -f1")
        if du and du ~= "" then
            result.stats.storage_used = du:gsub("%s+", "")
        end
    end
    
    -- 获取最后运行时间
    local last_run_file = output_dir .. "/data/last_run.txt"
    if fs.access(last_run_file) then
        local content = fs.readfile(last_run_file)
        if content then
            result.last_run = content:gsub("%s+$", "")
        end
    end

    -- 读取运行时状态
    local status_file = output_dir .. "/data/status.json"
    if fs.access(status_file) then
        local content = fs.readfile(status_file)
        if content and content ~= "" then
            local jsonc = require("luci.jsonc")
            local parsed = jsonc.parse(content)
            if parsed then
                result.runtime = parsed
            end
        end
    end

    -- 最近错误（结构化）
    if result.runtime and result.runtime.last_error and result.runtime.last_error ~= "" then
        table.insert(result.recent_errors, result.runtime.last_error)
    end
    
    http.prepare_content("application/json")
    http.write_json(result)
end

function action_logs()
    local uci = require("luci.model.uci").cursor()
    local main = uci:get_all("pixiv-backup", "settings")
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    write_luci_audit(output_dir, "controller", "logs", "ok", "query_logs")
    local latest_log = sys.exec("ls -t '" .. output_dir .. "/data/logs/'pixiv-backup-*.log 2>/dev/null | head -n 1")
    latest_log = latest_log and latest_log:gsub("%s+$", "")

    local logs = nil
    if latest_log and latest_log ~= "" and fs.access(latest_log) then
        logs = sys.exec("tail -200 '" .. latest_log .. "' 2>/dev/null")
    end
    
    http.prepare_content("text/plain; charset=utf-8")
    http.write(logs or "暂无日志")
end

function action_start()
    local uci = require("luci.model.uci").cursor()

    local main = uci:get_all("pixiv-backup", "settings")
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    local rc = sys.call("pixiv-backup start --force-run >/tmp/pixiv-backup-start.log 2>&1")
    local result = fs.readfile("/tmp/pixiv-backup-start.log") or ""
    write_luci_audit(output_dir, "controller", "start_force_run", rc == 0 and "ok" or "error", result ~= "" and result or "no_output")
    http.prepare_content("text/plain; charset=utf-8")
    http.write(result ~= "" and result or "已请求立即开始备份")
end

function action_stop()
    local rc = sys.call("pixiv-backup stop >/tmp/pixiv-backup-stop.log 2>&1")
    local result = fs.readfile("/tmp/pixiv-backup-stop.log") or ""
    local uci = require("luci.model.uci").cursor()
    local main = uci:get_all("pixiv-backup", "settings")
    local output_dir = main and main.output_dir or "/mnt/sda1/pixiv-backup"
    write_luci_audit(output_dir, "controller", "stop", rc == 0 and "ok" or "error", result ~= "" and result or "no_output")
    http.prepare_content("text/plain; charset=utf-8")
    http.write(result ~= "" and result or "服务停止命令已执行")
end
