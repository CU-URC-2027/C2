#!/usr/bin/env python3
"""Opt-in private development TCP forward; keeps application HTTP loopback-bound.

Use only on a trusted VM network. Exact source peers are required; no discovery,
credentials, control transformations or application state live in this utility.
"""
import argparse
import asyncio
import ipaddress


def address(value):
    ip=ipaddress.IPv4Address(value)
    if ip.is_unspecified or ip.is_multicast or not (ip.is_private or ip.is_loopback):
        raise argparse.ArgumentTypeError('Use explicit loopback/private IPv4')
    return str(ip)


async def serve(args):
    active=set()
    async def accept(reader,writer):
        task=asyncio.current_task();active.add(task);remote=None
        try:
            peer=writer.get_extra_info('peername')
            if not peer or peer[0] not in args.allow_peer or len(active)>32:return
            incoming,remote=await asyncio.wait_for(asyncio.open_connection(args.target,args.target_port),3)
            async def copy(source,sink):
                while True:
                    data=await asyncio.wait_for(source.read(32768),120)
                    if not data:return
                    sink.write(data);await asyncio.wait_for(sink.drain(),3)
            directions=[asyncio.create_task(copy(reader,remote)),asyncio.create_task(copy(incoming,writer))]
            try:await asyncio.wait(directions,return_when=asyncio.FIRST_COMPLETED)
            finally:
                for direction in directions:direction.cancel()
                await asyncio.gather(*directions,return_exceptions=True)
        except (OSError,TimeoutError):pass
        finally:
            for connection in (writer,remote):
                if connection:
                    connection.close()
                    try:await asyncio.wait_for(connection.wait_closed(),1)
                    except (OSError,TimeoutError):pass
            active.discard(task)
    server=await asyncio.start_server(accept,args.listen,args.port)
    print(f'Private preview forward {args.listen}:{args.port} -> {args.target}:{args.target_port}; peers {args.allow_peer}',flush=True)
    try:
        async with server:await server.serve_forever()
    finally:
        for task in tuple(active):task.cancel()
        await asyncio.gather(*tuple(active),return_exceptions=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--listen',type=address,default='127.0.0.1')
    p.add_argument('--port',type=int,required=True)
    p.add_argument('--target',type=address,required=True)
    p.add_argument('--target-port',type=int,required=True)
    p.add_argument('--allow-peer',type=address,action='append',required=True)
    args=p.parse_args()
    if any(not 1024<=n<=65535 for n in (args.port,args.target_port)):p.error('Use ports 1024–65535')
    try:asyncio.run(serve(args))
    except KeyboardInterrupt:pass


if __name__=='__main__':main()
