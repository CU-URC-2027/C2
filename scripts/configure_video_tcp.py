#!/usr/bin/env python3
"""Generate opt-in Fast DDS TCP profiles for one application process per VM."""
import argparse
import ipaddress
from pathlib import Path
import shlex


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('role',choices=('c2','rover'))
    p.add_argument('--address',required=True,type=ipaddress.IPv4Address)
    p.add_argument('--c2-address',required=True,type=ipaddress.IPv4Address)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--overlay',required=True,type=Path)
    p.add_argument('--domain',type=int,default=198)
    a=p.parse_args()
    if not 0<=a.domain<=232:p.error('Use ROS domain 0–232')
    for ip in (a.address,a.c2_address):
        if not ip.is_private or ip.is_unspecified or ip.is_multicast:p.error('Use private unicast addresses')
    a.output.mkdir(parents=True,exist_ok=True)
    locator=f'<locator><tcpv4><address>{a.c2_address}</address><physical_port>5100</physical_port><port>5100</port></tcpv4></locator>'
    server=a.role=='c2'
    xml=f'''<?xml version="1.0" encoding="UTF-8"?>
<dds xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles"><profiles>
<transport_descriptors><transport_descriptor>
<transport_id>urc_video_tcp</transport_id><type>TCPv4</type>
<interfaceWhiteList><address>{a.address}</address></interfaceWhiteList>
{'<listening_ports><port>5100</port></listening_ports>' if server else ''}
<enable_tcp_nodelay>true</enable_tcp_nodelay>
</transport_descriptor></transport_descriptors>
<participant profile_name="urc_video_{a.role}" is_default_profile="true"><rtps>
<userTransports><transport_id>urc_video_tcp</transport_id></userTransports><useBuiltinTransports>false</useBuiltinTransports>
{f'<defaultUnicastLocatorList>{locator}</defaultUnicastLocatorList>' if server else ''}
<builtin>{f'<metatrafficUnicastLocatorList>{locator}</metatrafficUnicastLocatorList>' if server else f'<initialPeersList>{locator}</initialPeersList>'}</builtin>
</rtps></participant></profiles></dds>
'''
    path=a.output.resolve()/'tcp.xml';path.write_text(xml)
    env=f'''# Explicit prototype environment. One participant per role; no chassis connection.
source /opt/ros/jazzy/setup.bash
source {shlex.quote(str(a.overlay.resolve()/'setup.bash'))}
export ROS_DOMAIN_ID={a.domain}
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export RMW_FASTRTPS_PUBLICATION_MODE=ASYNCHRONOUS
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS ROS_LOCALHOST_ONLY FASTDDS_BUILTIN_TRANSPORTS ROS_DISCOVERY_SERVER
export FASTRTPS_DEFAULT_PROFILES_FILE={shlex.quote(str(path))}
'''
    (a.output/'env.bash').write_text(env)
    print(a.output/'env.bash')


if __name__=='__main__':main()
