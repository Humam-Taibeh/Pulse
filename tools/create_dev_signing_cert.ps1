<#
.SYNOPSIS
    Create a LOCAL, TEST-ONLY Authenticode certificate for exercising
    build_release.ps1's -SignThumbprint signing path.

.DESCRIPTION
    THIS DOES NOT FIX SMARTSCREEN OR SMART APP CONTROL FOR ANYONE BUT THE
    MACHINE THAT RUNS IT. Read that twice before using this for anything
    other than testing the signing pipeline itself.

    SmartScreen and Smart App Control trust a binary because its signing
    certificate chains to a Certificate Authority that Microsoft's trust
    program recognises, and - separately - because the exact file hash or
    publisher has enough download reputation. A self-signed certificate
    chains to nothing: every machine that has not been individually told to
    trust THIS specific certificate sees exactly what it saw before -
    signed, but by nobody it recognises. Signing with it does not reduce a
    single warning for anyone who downloads PULSE_Setup.exe from GitHub.

    What it IS good for: proving that build_release.ps1's signing step,
    signtool's invocation, and the resulting Authenticode signature are all
    mechanically correct - so that the day a real certificate exists (see
    ROADMAP.md, "Code signing via Azure Trusted Signing"), swapping the
    thumbprint is the only change needed. Self-signed dev certificates are
    the normal way to test a signing pipeline before a paid one exists;
    treating the test as the fix is the mistake this header exists to head
    off.

    The certificate is written to the CURRENT USER'S certificate store
    (Cert:\CurrentUser\My) with a 3-year expiry and is never written to the
    repository - nothing here is meant to be committed.

.PARAMETER TrustLocally
    Also add the certificate to this machine's OWN Trusted Root and Trusted
    Publishers stores (CurrentUser scope only), so THIS machine's own
    SmartScreen/AppLocker/WDAC evaluation treats a PULSE build signed with
    it as chain-valid - useful for testing local policy behaviour. This
    changes trust on THIS machine only; it has no effect anywhere else and
    must never be presented to a user as something to do on their machine.

    WITHOUT this switch, signtool sign still succeeds - a self-signed
    certificate is a perfectly valid signature - but signtool verify (and
    build_release.ps1's own post-sign check) correctly reports the chain as
    untrusted, because nothing has told this machine to trust it. That is
    the expected result, not a bug: it is the same "signed but not trusted"
    state every downloader would see.

    Adding a certificate to the Root store shows Windows' own security
    confirmation dialog ("Do you want to install this certificate?") - run
    this interactively, not from an unattended/non-interactive session, or
    the Root addition will sit waiting for a click that never comes.

.PARAMETER Subject
    The certificate's subject name. Defaults to the publisher name main.spec
    and installer\pulse.iss already use, so a signed dev build's Properties
    dialog reads consistently with a real signed build's.

.EXAMPLE
    .\tools\create_dev_signing_cert.ps1
    .\tools\build_release.ps1 -SignThumbprint <thumbprint from the output>
#>
[CmdletBinding()]
param(
    [switch]$TrustLocally,
    [string]$Subject = 'CN=Humam Taibeh (PULSE dev signing - NOT for distribution)'
)

$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host '==> Creating a LOCAL, TEST-ONLY code-signing certificate' -ForegroundColor Cyan
Write-Host '    This does not make SmartScreen or Smart App Control trust PULSE' -ForegroundColor Yellow
Write-Host '    for anyone except this machine, and only if -TrustLocally is used.' -ForegroundColor Yellow
Write-Host ''

$Cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -CertStoreLocation 'Cert:\CurrentUser\My' `
    -KeyUsage DigitalSignature `
    -KeyAlgorithm RSA `
    -KeyLength 2048 `
    -NotAfter (Get-Date).AddYears(3) `
    -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3')   # EKU: Code Signing

Write-Host "    subject       $($Cert.Subject)"
Write-Host "    thumbprint    $($Cert.Thumbprint)"
Write-Host "    valid until   $($Cert.NotAfter.ToString('yyyy-MM-dd'))"

if ($TrustLocally) {
    Write-Host ''
    Write-Host '==> Trusting it on THIS machine only (CurrentUser store)' -ForegroundColor Cyan
    $DerBytes = $Cert.Export('Cert')
    foreach ($StoreName in @('Root', 'TrustedPublisher')) {
        $Store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
            $StoreName, 'CurrentUser')
        $Store.Open('ReadWrite')
        try {
            $Store.Add([System.Security.Cryptography.X509Certificates.X509Certificate2]::new($DerBytes))
            Write-Host "    added to CurrentUser\$StoreName"
        }
        finally {
            $Store.Close()
        }
    }
}

Write-Host ''
Write-Host '==> Next' -ForegroundColor Cyan
Write-Host "    .\tools\build_release.ps1 -SignThumbprint $($Cert.Thumbprint)"
Write-Host ''
Write-Host '    To remove this certificate later:' -ForegroundColor DarkGray
Write-Host "      Remove-Item Cert:\CurrentUser\My\$($Cert.Thumbprint)" -ForegroundColor DarkGray
if ($TrustLocally) {
    Write-Host "      Remove-Item Cert:\CurrentUser\Root\$($Cert.Thumbprint)" -ForegroundColor DarkGray
    Write-Host "      Remove-Item Cert:\CurrentUser\TrustedPublisher\$($Cert.Thumbprint)" -ForegroundColor DarkGray
}
