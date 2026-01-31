module("luci.controller.pixiv-backup", package.seeall)

function index()
    entry({"admin", "services", "pixiv-backup"}, cbi("pixiv-backup"), _("Pixiv备份"), 60).dependent = false
    entry({"admin", "services", "pixiv-backup", "status"}, call("action_status"), _("状态"), 10).leaf = true
    entry({"admin", "services", "pixiv-backup", "logs"}, call("action_logs"), _("日志"), 20).leaf = true
    entry({"admin", "services", "pixiv-backup", "start"}, call("action_start"), _("开始备份"), 30).leaf = true
    entry({"admin", "services", "pixiv-backup", "stop"}, call("action_stop"), _("停止备份"), 40).leaf = true
end

function action_status()
    local uci = require("luci.model.uci").cursor()
    local json = require("luci.json")
    local sys = require("luci.sys")
    
    local result = {
        service_status = "stopped",
        config_status = "unconfigured",
        last_run = nil,
        stats = {
            total_downloaded = 0,
            last_24h = 0,
            storage_used = "0MB"
        }
    }
    
    -- 检查服务状态
    local service_pid = sys.exec("pgrep -f 'pixiv-backup'")
    if service_pid and service_pid ~= "" then
        result.service_status = "running"
    end
    
    -- 检查配置
    uci:foreach("pixiv-backup", "main", function(s)
        if s.enabled == "1" and s.user_id and s.user_id ~= "" and s.refresh_token and s.refresh_token ~= "" then
            result.config_status = "configured"
        end
    end)
    
    -- 获取统计数据
    local db_path = "/mnt/sda1/pixiv-backup/data/pixiv.db"
    if nixio.fs.access(db_path) then
        local count = sys.exec("sqlite3 '" .. db_path .. "' 'SELECT COUNT(*) FROM illusts;' 2>/dev/null")
        if count and count ~= "" then
            result.stats.total_downloaded = tonumber(count) or 0
        end
        
        -- 计算存储使用量
        local du = sys.exec("du -sh /mnt/sda1/pixiv-backup/img/ 2>/dev/null | cut -f1")
        if du and du ~= "" then
            result.stats.storage_used = du:gsub("%s+", "")
        end
    end
    
    -- 获取最后运行时间
    local last_run_file = "/mnt/sda1/pixiv-backup/data/last_run.txt"
    if nixio.fs.access(last_run_file) then
        result.last_run = sys.exec("cat '" .. last_run_file .. "' 2>/dev/null")
    end
    
    luci.http.prepare_content("application/json")
    luci.http.write_json(result)
end

function action_logs()
    local sys = require("luci.sys")
    local log_file = "/var/log/pixiv-backup.log"
    
    if not nixio.fs.access(log_file) then
        luci.http.write("暂无日志")
        return
    end
    
    local logs = sys.exec("tail -50 '" .. log_file .. "' 2>/dev/null")
    luci.http.prepare_content("text/plain")
    luci.http.write(logs or "无法读取日志")
end

function action_start()
    local sys = require("luci.sys")
    local result = sys.exec("/etc/init.d/pixiv-backup start 2>&1")
    luci.http.prepare_content("text/plain")
    luci.http.write(result)
end

function action_stop()
    local sys = require("luci.sys")
    local result = sys.exec("/etc/init.d/pixiv-backup stop 2>&1")
    luci.http.prepare_content("text/plain")
    luci.http.write(result)
end