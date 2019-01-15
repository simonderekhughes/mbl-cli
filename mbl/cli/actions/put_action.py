#!/usr/bin/env python3
# Copyright (c) 2018 Arm Limited and Contributors. All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Put action handler."""


import sys

from mbl.cli.utils import ssh

from . import utils


def execute(args):
    """Entry point for the put action."""
    dev = utils.create_device(args)
    print(f"Putting {args.src_path} on device: {dev.hostname}\n")

    with ssh.SSHSession(dev) as ssh_session:
        ssh_session.put(local_path=args.src_path, remote_path=args.dst_path)

    print("\n\nCompleted without error.")