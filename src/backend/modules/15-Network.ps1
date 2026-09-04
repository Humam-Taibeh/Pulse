#Requires -Version 5.1
<#
.SYNOPSIS
    15-Network.ps1 - per-adapter DNS profile switching (v1.0+ Phase 2, F4).

.DESCRIPTION
    Switching a PC to Cloudflare, Quad9 or AdGuard is one of the few
    single changes that improves speed AND privacy at once, and doing it
    by hand means five nested adapter dialogs per machine. This is that
    change, per adapter, with a real way back.

    THREE RULES THIS MODULE IS BUILT ON:

    1. REVERSIBLE, ALWAYS. Every profile below has a counterpart:
       Restore-PulseDnsDefaults resets the adapter to DHCP-provided DNS,
       which is the state Windows shipped in. A network tool that can
       strand a machine off the internet with no undo is not a tool, it
       is a hazard - so the undo is a first-class task with its own card,
       not a footnote.

    2. PER ADAPTER, NEVER "ALL". A laptop has Wi-Fi, Ethernet, and often
       a VPN or Hyper-V virtual switch. Rewriting DNS across all of them
       breaks the VPN's split-DNS and the virtual switch's host
       resolution, and the user asked to change ONE connection. The GUI
       picks the adapter; this module changes only what it is given.

    3. NOTHING IS RESOLVED HERE. The module writes addresses. It does not
       query them, test them, or phone anything to "verify" a profile -
       the DNS servers below are constants, published by their operators,
       and a privacy tool that made a network round trip to prove its
       privacy setting worked would be self-defeating.

    ADMIN IS REQUIRED and gated up front by the dispatcher: DNS
    configuration lives in the adapter's machine-scope settings.
#>

# ============================================================
#  THE PROFILES
# ============================================================
# Published, documented resolver addresses. Both IPv4 and IPv6 are set
# where the operator publishes them: leaving IPv6 pointed at the old
# resolver on a dual-stack machine means half the lookups quietly ignore
# the profile the user just chose - the failure mode that makes people
# think DNS changes "did nothing".
#
# `doh` is the operator's DNS-over-HTTPS template. Windows 11 (build
# 22000+) can encrypt queries to these resolvers; Windows 10 cannot, and
# Set-PulseDnsProfile reports that honestly rather than silently skipping.
$Script:DnsProfiles = @(
    @{ Key = "cloudflare"; Name = "Cloudflare"
       Note = "Fast, privacy-focused. No query logging."
       V4 = @("1.1.1.1", "1.0.0.1")
       V6 = @("2606:4700:4700::1111", "2606:4700:4700::1001")
       Doh = "https://cloudflare-dns.com/dns-query" }
    @{ Key = "cloudflare-family"; Name = "Cloudflare (Malware Blocking)"
       Note = "Cloudflare, with known malware domains blocked."
       V4 = @("1.1.1.2", "1.0.0.2")
       V6 = @("2606:4700:4700::1112", "2606:4700:4700::1002")
       Doh = "https://security.cloudflare-dns.com/dns-query" }
    @{ Key = "quad9"; Name = "Quad9"
       Note = "Blocks known-malicious domains. Swiss non-profit."
       V4 = @("9.9.9.9", "149.112.112.112")
       V6 = @("2620:fe::fe", "2620:fe::9")
       Doh = "https://dns.quad9.net/dns-query" }
    @{ Key = "google"; Name = "Google Public DNS"
       Note = "Very fast and widely reachable. Google logs some data."
       V4 = @("8.8.8.8", "8.8.4.4")
       V6 = @("2001:4860:4860::8888", "2001:4860:4860::8844")
       Doh = "https://dns.google/dns-query" }
    @{ Key = "adguard"; Name = "AdGuard DNS"
       Note = "Blocks ads and trackers at the DNS level."
       V4 = @("94.140.14.14", "94.140.15.15")
       V6 = @("2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff")
       Doh = "https://dns.adguard-dns.com/dns-query" }
)

function Get-DnsProfileByKey {
    param([Parameter(Mandatory)][string]$Key)
    return ($Script:DnsProfiles | Where-Object { $_.Key -eq $Key } | Select-Object -First 1)
}

function Test-DohSupported {
    <# DoH client support landed in Windows 11 (build 22000). Reported as
       a capability rather than attempted-and-caught: a user who picked an
       encrypted profile deserves to be told their OS cannot encrypt,
       not to have it silently downgraded to plaintext. #>
    try {
        return ([Environment]::OSVersion.Version.Build -ge 22000) -and
               ($null -ne (Get-Command Add-DnsClientDohServerAddress -ErrorAction SilentlyContinue))
    } catch {
        return $false
    }
}

# ============================================================
#  READ
# ============================================================
function Get-PulseNetworkAdapters {
    <# Every real, connected adapter with its current DNS. READ-ONLY.

       Loopback and tunnel adapters are filtered out: they are not
       connections a user thinks of as "my internet", and offering to
       rewrite their DNS is offering to break something invisible. #>
    $result = @()
    try {
        $adapters = @(Get-NetAdapter -Physical -ErrorAction Stop |
            Where-Object { $_.Status -eq 'Up' })
    } catch {
        return @()
    }

    foreach ($adapter in $adapters) {
        $v4 = @(); $v6 = @()
        try {
            $servers = @(Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ErrorAction Stop)
            $v4 = @(($servers | Where-Object { $_.AddressFamily -eq 2 }).ServerAddresses)
            $v6 = @(($servers | Where-Object { $_.AddressFamily -eq 23 }).ServerAddresses)
        } catch { }

        # Which published profile, if any, this adapter is currently on -
        # so the GUI can show the active one rather than making the user
        # compare IP addresses by eye.
        $active = "custom"
        if ($v4.Count -eq 0) {
            $active = "dhcp"
        } else {
            foreach ($dnsProfile in $Script:DnsProfiles) {
                $expected = @($dnsProfile.V4 | Sort-Object)
                $actual = @($v4 | Sort-Object)
                if ((@(Compare-Object $expected $actual -SyncWindow 0).Count -eq 0)) {
                    $active = $dnsProfile.Key
                    break
                }
            }
        }

        $result += [PSCustomObject]@{
            name        = [string]$adapter.Name
            description = [string]$adapter.InterfaceDescription
            ifIndex     = [int]$adapter.ifIndex
            v4          = $v4
            v6          = $v6
            activeKey   = $active
        }
    }
    return $result
}

function Get-PulseNetworkReport {
    <# The whole F4 document: adapters, the profile catalog, and whether
       this OS can do encrypted DNS. #>
    return [PSCustomObject]@{
        generatedAt  = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        dohSupported = Test-DohSupported
        adapters     = @(Get-PulseNetworkAdapters)
        profiles     = @($Script:DnsProfiles | ForEach-Object {
            [PSCustomObject]@{
                key = $_.Key; name = $_.Name; note = $_.Note
                v4 = $_.V4; v6 = $_.V6
            }
        })
    }
}

# ============================================================
#  WRITE
# ============================================================
function Resolve-PulseAdapter {
    <# An adapter object from a NAME, or $null. Looked up by name rather
       than trusting an interface index from the GUI: indexes are
       reassigned when adapters are added or removed, so a stale one could
       address a completely different connection. #>
    param([Parameter(Mandatory)][string]$Name)
    try {
        return (Get-NetAdapter -Name $Name -ErrorAction Stop | Select-Object -First 1)
    } catch {
        return $null
    }
}

function Set-PulseDnsProfile {
    <# Point one adapter at one published profile. #>
    param(
        [Parameter(Mandatory)][string]$AdapterName,
        [Parameter(Mandatory)][string]$ProfileKey
    )

    $dnsProfile = Get-DnsProfileByKey -Key $ProfileKey
    if (-not $dnsProfile) {
        Write-ErrorX "Unknown DNS profile '$ProfileKey'."
        return $false
    }
    $adapter = Resolve-PulseAdapter -Name $AdapterName
    if (-not $adapter) {
        Write-ErrorX "Network adapter '$AdapterName' was not found or is not connected."
        return $false
    }

    if ($Script:DryRun) {
        Write-Host "   [WHATIF] Set $AdapterName DNS to $($dnsProfile.Name) ($($dnsProfile.V4 -join ', '))"
        Write-Host "   [WHATIF] Set $AdapterName IPv6 DNS to $($dnsProfile.V6 -join ', ')"
        return $true
    }

    try {
        # IPv4 and IPv6 are set in ONE call each, with the full list: the
        # cmdlet REPLACES the address list rather than appending, so
        # passing both servers together is what makes the secondary a
        # secondary instead of wiping it.
        Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex `
            -ServerAddresses $dnsProfile.V4 -ErrorAction Stop
        Write-Success "$AdapterName -> $($dnsProfile.Name) ($($dnsProfile.V4 -join ', '))"
    } catch {
        Write-ErrorX "Could not set IPv4 DNS on '$AdapterName': $($_.Exception.Message)"
        return $false
    }

    try {
        Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex `
            -ServerAddresses $dnsProfile.V6 -ErrorAction Stop
    } catch {
        # Non-fatal by design: a machine with IPv6 unbound on this adapter
        # is a normal configuration, and the IPv4 change above already
        # did what the user asked.
        Write-Host "   IPv6 DNS was not set (IPv6 may be disabled on this adapter)."
    }

    if (Test-DohSupported) {
        try {
            foreach ($server in $dnsProfile.V4) {
                Add-DnsClientDohServerAddress -ServerAddress $server `
                    -DohTemplate $dnsProfile.Doh -AllowFallbackToUdp $false `
                    -AutoUpgrade $true -ErrorAction Stop
            }
            Write-Host "   Encrypted DNS (DoH) enabled for this resolver."
        } catch {
            # Already registered is the common case and is not a failure.
            Write-Host "   DoH template was already registered for this resolver."
        }
    }

    # The cache still holds answers from the previous resolver; without
    # this the change appears not to have worked for several minutes.
    try { Clear-DnsClientCache -ErrorAction Stop } catch { }
    return $true
}

function Restore-PulseDnsDefaults {
    <# Hand the adapter back to DHCP - the state Windows shipped in.

       This is the undo for Set-PulseDnsProfile and the reason that
       function is safe to offer at all. #>
    param([Parameter(Mandatory)][string]$AdapterName)

    $adapter = Resolve-PulseAdapter -Name $AdapterName
    if (-not $adapter) {
        Write-ErrorX "Network adapter '$AdapterName' was not found or is not connected."
        return $false
    }

    if ($Script:DryRun) {
        Write-Host "   [WHATIF] Reset $AdapterName DNS to DHCP-provided servers"
        return $true
    }

    try {
        Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex `
            -ResetServerAddresses -ErrorAction Stop
        Write-Success "$AdapterName -> automatic (DHCP-provided) DNS"
    } catch {
        Write-ErrorX "Could not reset DNS on '$AdapterName': $($_.Exception.Message)"
        return $false
    }
    try { Clear-DnsClientCache -ErrorAction Stop } catch { }
    return $true
}

# ============================================================
#  CONNECTIVITY DIAGNOSTICS, STACK RESET AND DRIVER CHECK
#  (Pillar 3 - "Essential Runtimes & Hardware Drivers")
#
#  These three sit beside the DNS switcher above because they answer the
#  same question from three different depths: my connection is wrong. DNS
#  is the shallowest cause, a corrupted Winsock catalog is the deepest,
#  and an out-of-date Ethernet/Wi-Fi driver is the one no software fix
#  reaches at all.
#
#  ONLY ONE OF THE THREE WRITES ANYTHING. The report and the driver check
#  are read-only and deliberately NOT admin-gated (see the note in
#  $Script:AdminRequiredTasks) - asking what hardware is fitted should
#  never raise a UAC prompt. Reset-PulseNetworkStack is the write, and it
#  is gated.
# ============================================================

function Get-PulseAdapterDiagnostics {
    <# Every physical adapter - up or down - with the facts a connection
       problem is actually diagnosed from: link state and speed, the
       addresses it holds, its gateway, and the driver behind it.

       PHYSICAL BUT NOT ONLY 'Up', which is the difference from
       Get-PulseNetworkAdapters above. That one lists connections whose
       DNS can be rewritten, so a down adapter is noise. Here a DOWN
       adapter is frequently the whole answer - "your Ethernet cable is
       not connected" is the diagnosis - so filtering it out would hide
       the finding. #>
    $result = @()
    try {
        $adapters = @(Get-NetAdapter -Physical -ErrorAction Stop)
    } catch {
        return @()
    }
    foreach ($adapter in $adapters) {
        $v4 = @(); $gateway = ""
        try {
            $v4 = @((Get-NetIPAddress -InterfaceIndex $adapter.ifIndex `
                        -AddressFamily IPv4 -ErrorAction Stop).IPAddress)
        } catch { }
        try {
            $gateway = [string]((Get-NetIPConfiguration -InterfaceIndex $adapter.ifIndex `
                        -ErrorAction Stop).IPv4DefaultGateway.NextHop | Select-Object -First 1)
        } catch { }
        $driverDate = ""
        if ($adapter.DriverDate) {
            try { $driverDate = ([datetime]$adapter.DriverDate).ToString('yyyy-MM-dd') } catch { }
        }
        $result += [PSCustomObject]@{
            name           = [string]$adapter.Name
            description    = [string]$adapter.InterfaceDescription
            status         = [string]$adapter.Status
            linkSpeed      = [string]$adapter.LinkSpeed
            driverVersion  = [string]$adapter.DriverVersion
            driverDate     = $driverDate
            driverProvider = [string]$adapter.DriverProvider
            addresses      = $v4
            gateway        = $gateway
        }
    }
    return $result
}

function Show-PulseAdapterDiagnostics {
    <# The read-only connectivity report, written to the live console and
       the operation log. Returns $true when at least one adapter is up -
       the only "verdict" this task can honestly reach, since everything
       else it prints is information rather than judgement. #>
    $adapters = @(Get-PulseAdapterDiagnostics)
    if ($adapters.Count -eq 0) {
        Write-Warn "No physical network adapters were found on this PC."
        return $false
    }

    $up = 0
    foreach ($adapter in $adapters) {
        Write-Host ""
        Write-StatusPanel -Label $adapter.status.ToUpper() -Text $adapter.name
        Write-Info "Adapter      : $($adapter.description)"
        if ($adapter.status -eq 'Up') {
            $up++
            Write-Info "Link speed   : $($adapter.linkSpeed)"
            if ($adapter.addresses.Count -gt 0) {
                Write-Info "IPv4 address : $($adapter.addresses -join ', ')"
            } else {
                Write-Warn "This adapter is up but holds no IPv4 address - DHCP may not have answered."
            }
            if ($adapter.gateway) {
                Write-Info "Gateway      : $($adapter.gateway)"
            } else {
                Write-Warn "No default gateway - this adapter can reach the local network but not the internet."
            }
        } else {
            Write-Info "This adapter is $($adapter.status.ToLower()) - nothing is connected to it."
        }
        $driver = $adapter.driverVersion
        if ($adapter.driverDate) { $driver = "$driver  ($($adapter.driverDate))" }
        Write-Info "Driver       : $driver"
        if ($adapter.driverProvider) { Write-Info "Provided by  : $($adapter.driverProvider)" }
    }

    Write-Host ""
    if ($up -eq 0) {
        Write-Warn "No adapter is currently connected."
    } else {
        Write-Success "$up of $($adapters.Count) adapter(s) connected."
    }
    return ($up -gt 0)
}

#: Official driver pages, by the vendor string an adapter reports.
#:
#: LINKS, NOT DOWNLOADS, and that is the whole design. A network driver is
#: the one component where a wrong or generic package can leave a machine
#: with no way to fetch the right one - so Pulse identifies the hardware
#: precisely and hands over to the vendor's own tool, rather than guessing
#: at an .inf and installing it. Windows Update is named first in the
#: report because on a working connection it is genuinely the right
#: answer; these are for when it is not.
$Script:NetworkDriverVendors = @(
    @{ Match = "Intel";            Name = "Intel Ethernet / Wi-Fi"
       Url   = "https://www.intel.com/content/www/us/en/download-center/home.html" }
    @{ Match = "Realtek";          Name = "Realtek Ethernet / Wi-Fi"
       Url   = "https://www.realtek.com/Download" }
    @{ Match = "Qualcomm|Atheros"; Name = "Qualcomm Atheros"
       Url   = "https://www.qualcomm.com/support" }
    @{ Match = "Broadcom";         Name = "Broadcom"
       Url   = "https://www.broadcom.com/support/download-search" }
    @{ Match = "MediaTek|Ralink";  Name = "MediaTek"
       Url   = "https://www.mediatek.com/products/broadband-wifi" }
)

function Show-PulseNetworkDriverCheck {
    <# Name every network adapter's driver and point at the vendor's own
       download page. READ-ONLY: nothing is fetched or installed.

       THE DATE IS THE CHECK THAT MATTERS. A network driver more than a
       couple of years old is the usual cause of the "connected but slow,
       drops under load" complaints that no amount of DNS or Winsock work
       will fix - and it is invisible in Windows' own UI unless you go
       looking in Device Manager. #>
    $adapters = @(Get-PulseAdapterDiagnostics)
    if ($adapters.Count -eq 0) {
        Write-Warn "No physical network adapters were found on this PC."
        return $false
    }

    Write-Info "Windows Update carries most network drivers - Settings > Windows Update > Advanced options > Optional updates is the first place to look."
    $stale = 0
    foreach ($adapter in $adapters) {
        Write-Host ""
        Write-StatusPanel -Label "ADAPTER" -Text $adapter.name
        Write-Info $adapter.description
        $driver = if ($adapter.driverVersion) { $adapter.driverVersion } else { "unknown" }
        Write-Info "Driver version: $driver"

        if ($adapter.driverDate) {
            $age = ((Get-Date) - [datetime]$adapter.driverDate).Days
            $years = [math]::Round($age / 365.0, 1)
            if ($age -gt 730) {
                $stale++
                Write-Warn "Driver dated $($adapter.driverDate) - about $years years old. Worth updating."
            } else {
                Write-Info "Driver dated $($adapter.driverDate) - about $years years old."
            }
        }

        $vendor = $null
        foreach ($candidate in $Script:NetworkDriverVendors) {
            if ($adapter.description -match $candidate.Match -or
                $adapter.driverProvider -match $candidate.Match) {
                $vendor = $candidate
                break
            }
        }
        if ($vendor) {
            Write-Info "Official drivers: $($vendor.Name) - $($vendor.Url)"
            Write-Log "NETWORK-DRIVER $($adapter.name): $($vendor.Name) -> $($vendor.Url)"
        } else {
            Write-Info "No vendor download page is mapped for this adapter - check your PC or motherboard maker's support page."
        }
    }

    Write-Host ""
    if ($stale -gt 0) {
        Write-Warn "$stale adapter driver(s) are over two years old."
    } else {
        Write-Success "Every network adapter driver is reasonably current."
    }
    return $true
}

function Reset-PulseNetworkStack {
    <# The deep repair: rebuild the Winsock catalog and the TCP/IP stack,
       then release/renew the lease and flush every cache around them.

       A REBOOT IS REQUIRED and this REPORTS it rather than performing it.
       Both netsh resets rewrite registry state the running stack has
       already loaded, so the machine is half-applied until it restarts -
       and a network tool that reboots a PC out from under someone is not
       a tool.

       DISTINCT FROM 'Network & Ping Optimizer', which flushes DNS and
       resets Winsock as a light-touch latency pass. This is the full
       teardown, including the IP stack and the adapter lease, and it is
       what you run when something is actually broken.

       ORDER MATTERS: winsock before ip (the ip reset re-registers
       providers the winsock reset just cleared), and the release/renew
       after both so the adapter takes its lease against the rebuilt
       stack rather than against the one being torn down. #>
    $Steps = @(
        @{ Label = "Resetting the Winsock catalog";   File = "netsh";    Args = @("winsock", "reset") }
        @{ Label = "Resetting the IPv4 stack";        File = "netsh";    Args = @("int", "ip", "reset") }
        @{ Label = "Resetting the IPv6 stack";        File = "netsh";    Args = @("int", "ipv6", "reset") }
        @{ Label = "Releasing the current IP lease";  File = "ipconfig"; Args = @("/release") }
        @{ Label = "Renewing the IP lease";           File = "ipconfig"; Args = @("/renew") }
        @{ Label = "Flushing the DNS resolver cache"; File = "ipconfig"; Args = @("/flushdns") }
        @{ Label = "Clearing the ARP cache";          File = "netsh";    Args = @("interface", "ip", "delete", "arpcache") }
    )

    if ($Script:DryRun) {
        foreach ($Step in $Steps) {
            [void](Test-DryRun "$($Step.Label): $($Step.File) $($Step.Args -join ' ')")
        }
        return $true
    }

    $failed = @()
    $Index = 0
    foreach ($Step in $Steps) {
        $Index++
        Write-GuiStage "[$Index/$($Steps.Count)] $($Step.Label)..."
        try {
            $Proc = Start-Process -FilePath $Step.File -ArgumentList $Step.Args `
                -NoNewWindow -Wait -PassThru -ErrorAction Stop
            # ipconfig /release and /renew return non-zero on an adapter
            # with no DHCP lease to release, which is not a failure of the
            # reset - it means there was nothing there. Only the netsh
            # resets are treated as load-bearing.
            if ($Proc.ExitCode -ne 0 -and $Step.File -eq "netsh") {
                $failed += $Step.Label
                Write-Warn "$($Step.Label) reported exit code $($Proc.ExitCode)."
            } else {
                Write-Success $Step.Label
            }
        } catch {
            $failed += $Step.Label
            Write-ErrorX "$($Step.Label) could not run: $($_.Exception.Message)"
        }
    }

    if ($failed.Count -gt 0) { return $false }
    $Script:PendingRestart = $true
    return $true
}
