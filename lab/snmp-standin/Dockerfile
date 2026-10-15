# lab/snmp-standin/Dockerfile -- hand-written (CLAUDE.md §5).
# A Linux SNMPv3 agent standing in for a switch until there is a CML lab.
# Not Cisco: IF-MIB, SNMPv2-MIB and ICMP behave like the real thing,
# Cisco MIBs (CPU, memory, sensors) do not exist here.
FROM alpine:3.20.3

RUN apk add --no-cache net-snmp iperf3

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 161/udp
ENTRYPOINT ["/entrypoint.sh"]
