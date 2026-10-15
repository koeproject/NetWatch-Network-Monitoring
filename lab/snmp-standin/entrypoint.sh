#!/bin/sh
# SNMPv3 authPriv only (SHA + AES128), same as catalog.SNMP_DETAILS and the
# switch config in phase-2-guide 2.5. Passphrases come from lab/snmp-standin/.env.
set -eu

: "${SNMP_USER:?}" "${SNMP_AUTH:?}" "${SNMP_PRIV:?}"

# -C below means snmpd reads only this file, so the user is created here too.
cat > /etc/snmp/snmpd.conf <<CONF
agentAddress udp:161
sysName ${HOSTNAME}
sysDescr NetWatch lab stand-in (net-snmp, not Cisco)
createUser ${SNMP_USER} SHA "${SNMP_AUTH}" AES "${SNMP_PRIV}"
rouser ${SNMP_USER} priv
CONF

# iperf3 server so another stand-in can push a known rate at us (2.6).
iperf3 -s -D

# -LS0-4d: log errors and warnings only (Docker's /proc/net/snmp layout makes
# systemstats print an "unexpected header length" notice on every poll).
exec snmpd -f -LS0-4d -C -c /etc/snmp/snmpd.conf
