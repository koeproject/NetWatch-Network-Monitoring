# lab/snmp-standin/standin.ps1 -- run the Phase 2 checks against net-snmp stand-ins.
# Needs the $PROFILE helpers (engine, Get-NwEnv) and the engine + backend running.
#
#   .\lab\snmp-standin\standin.ps1 up         # .env (random lab passphrases) + 3 containers
#   .\lab\snmp-standin\standin.ps1 provision  # provision.py with provisioning/lab-standin.csv
#   .\lab\snmp-standin\standin.ps1 macros     # lab passphrases as host secret macros + LLD now
#   .\lab\snmp-standin\standin.ps1 verify     # verify.py with the lab inventory
#   .\lab\snmp-standin\standin.ps1 down       # delete LAB-* hosts, their data in our store, containers
#
# The lab passphrases never touch the global {$SNMPV3.*} macros: they are set
# as host macros on LAB-CORE / LAB-ACC only, so real devices are unaffected.
param([Parameter(Mandatory)][ValidateSet("up", "provision", "macros", "verify", "down")][string]$Action)

$ErrorActionPreference = "Stop"
$root = Get-NwRoot
$lab = "$root/lab/snmp-standin"
$hosts = @("LAB-CORE", "LAB-ACC", "LAB-AP")
$snmpHosts = @("LAB-CORE", "LAB-ACC")

function Read-LabEnv {
  $vals = @{}
  Get-Content "$lab/.env" | ForEach-Object { $k, $v = $_ -split "=", 2; $vals[$k] = $v }
  return $vals
}

function Invoke-LabModule([string]$Module) {
  docker compose -f "$root/backend/docker-compose.dev.yml" run --rm `
    -v "${root}/provisioning:/srv/provisioning:ro" `
    -v "${root}/templates:/srv/templates:ro" `
    -e "NETWATCH_INVENTORY=/srv/provisioning/lab-standin.csv" `
    -e "ENGINE_TOKEN=$(Get-NwEnv ENGINE_TOKEN)" backend python -m $Module
}

switch ($Action) {
  "up" {
    if (-not (Test-Path "$lab/.env")) {
      $user = (engine usermacro.get @{ output = @("value"); globalmacro = $true; filter = @{ macro = '{$SNMPV3.USER}' } })[0].value
      $rand = { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) }
      "SNMP_USER=$user", "SNMP_AUTH=$(& $rand)", "SNMP_PRIV=$(& $rand)" | Set-Content -Encoding ascii "$lab/.env"
      "created $lab/.env (gitignored)"
    }
    docker compose -f "$lab/docker-compose.yml" up -d --build
  }
  "provision" { Invoke-LabModule provisioning.provision }
  "verify" { Invoke-LabModule provisioning.verify }
  "macros" {
    $vals = Read-LabEnv
    foreach ($h in $snmpHosts) {
      $id = (engine host.get @{ output = @("hostid"); filter = @{ host = @($h) } })[0].hostid
      $have = @(engine usermacro.get @{ hostids = @($id); output = @("hostmacroid") })
      if ($have.Count) { engine usermacro.delete @($have | ForEach-Object hostmacroid) | Out-Null }
      engine usermacro.create @(
        @{ hostid = $id; macro = '{$SNMPV3.AUTH}'; value = $vals.SNMP_AUTH; type = 1; description = "lab stand-in only" },
        @{ hostid = $id; macro = '{$SNMPV3.PRIV}'; value = $vals.SNMP_PRIV; type = 1; description = "lab stand-in only" }
      ) | Out-Null
      "$h host macros set"
    }
    # Polls failed before the macros existed, so the engine has SNMP marked
    # unavailable; a "check now" sent before it recovers is dropped.
    foreach ($h in $snmpHosts) {
      $deadline = (Get-Date).AddMinutes(3)
      do {
        $host_ = (engine host.get @{ output = @("hostid"); filter = @{ host = @($h) }; selectInterfaces = @("available") })[0]
        if ($host_.interfaces[0].available -eq "1") { break }
        Start-Sleep -Seconds 10
      } while ((Get-Date) -lt $deadline)
      if ($host_.interfaces[0].available -ne "1") { throw "$h SNMP still not available after 3 min (check .env vs host macros)" }
      # type 6 = "check now"; LLD otherwise waits up to an hour.
      $rules = engine discoveryrule.get @{ hostids = @($host_.hostid); output = @("itemid") }
      engine task.create @($rules | ForEach-Object { @{ type = 6; request = @{ itemid = $_.itemid } } }) | Out-Null
      "$h SNMP available, discovery queued"
    }
  }
  "down" {
    $ids = @(engine host.get @{ output = @("hostid"); filter = @{ host = $hosts } } | ForEach-Object hostid)
    if ($ids.Count) { engine host.delete $ids | Out-Null; "deleted $($ids.Count) LAB hosts from the engine" }
    # The engine sends no recovery for deleted hosts, so clear their rows in our store too.
    $sql = "DELETE FROM metric_points WHERE device_ref LIKE 'LAB-%'; DELETE FROM latest_values WHERE device_ref LIKE 'LAB-%'; DELETE FROM problems WHERE device_ref LIKE 'LAB-%';"
    # SQL on stdin: PowerShell 5.1 mangles double quotes inside native-command arguments.
    $sql | docker exec -i NetWatch-db sh -c 'psql -U $POSTGRES_USER -d acme'
    docker compose -f "$lab/docker-compose.yml" down
  }
}
