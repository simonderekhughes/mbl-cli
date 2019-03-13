#!/usr/bin/env python3
# Copyright (c) 2019 Arm Limited and Contributors. All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""pelion-status action handler."""

import shlex

from mbl.cli.utils.ssh import SSHCallError, SSHSession

from . import utils


def execute(args):
    """Entry point for the get-pelion-status command."""
    device = utils.create_device(args.address)
    with SSHSession(device) as ssh:
        try:
            ssh.run_cmd(
                "{} --get-pelion-status".format(
                    shlex.quote(utils.PROVISIONING_UTIL_PATH)
                ),
                check=True,
                writeout=True,
            )
        except SSHCallError:
            raise PelionConfigurationError(
                "Your device is not correctly configured for Pelion Device "
                "Management. You must provision your device using the "
                "provision-pelion command."
            )


class PelionConfigurationError(Exception):
    """Device is not configured correctly for Pelion device management."""