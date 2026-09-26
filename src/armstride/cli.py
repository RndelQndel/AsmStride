"""Single-process, loopback-only local launcher."""

import argparse

import uvicorn

from armstride.app import create_app


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the local ArmStride application.')
    parser.add_argument('--port', type=int, default=8000, help='Loopback HTTP port (default: 8000).')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    print(f'ArmStride: http://127.0.0.1:{args.port}', flush=True)
    uvicorn.run(create_app(), host='127.0.0.1', port=args.port, workers=1, proxy_headers=False)


if __name__ == '__main__':
    main()
