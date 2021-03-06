#!/usr/bin/env python3
# Copyright (c) 2018 Arm Limited and Contributors. All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Handle ssh connections and data transfer."""


import functools
import logging
import pathlib
import platform
import time

import paramiko
import scp

from . import shell

logging.getLogger("paramiko").setLevel(logging.CRITICAL)

SUPPRESS_PROGRESS = False


def scp_progress(filename, size, sent):
    """Display the progress of an scp transfer."""
    if sent and not SUPPRESS_PROGRESS:
        try:
            fname = filename.decode()
        except AttributeError:
            fname = filename
        print(
            "\r{} is transferring. Progress {:2.1%}".format(
                fname, sent / size
            ),
            end="\r",
        )
        # vt100 escape sequence to clear current line
        # http://ascii-table.com/ansi-escape-sequences-vt-100.php
        # this will not work on a Windows cmd line, as it doesn't
        # have vt100 support by default.
        # TODO: Windows solution.
        print("\x1b[2K", end="")


def _scp_session(transfer_func):
    """Start an scp session on the client.

    Teardown the SCP session when the SCPClient context manager exits.

    This decorator can only be used with methods of the SSHSession class.
    """
    # retain metadata from the wrapped function 'object'.
    @functools.wraps(transfer_func)
    def wrapper(self, local_path, remote_path, recursive=False):
        with scp.SCPClient(
            self._client.get_transport(), progress=scp_progress
        ) as scp_client:
            transfer_func(
                self,
                local_path=local_path,
                remote_path=remote_path,
                scp_client=scp_client,
                recursive=recursive,
            )

    return wrapper


class SSHClientWithNoAuthSupport(paramiko.SSHClient):
    """SSH Client which handles 'no auth' SSH devices."""

    def _auth(self, username, *args):
        """Override to invoke the transport directly when SSH auth is None."""
        try:
            self._transport.auth_none(username)
        except paramiko.SSHException:
            super()._auth(username, *args)


class SSHSession:
    """Context manager wrapping an SSHClient, handles setup/auth and scp."""

    def __init__(self, device):
        """:param device DeviceInfo: A device info object."""
        self.device = device
        self._client = SSHClientWithNoAuthSupport()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def __enter__(self):
        """Enter the context, connect to the ssh session."""
        self._connect()
        return self

    def __exit__(self, *exception_info):
        """Exit the context, ensuring the ssh client is closed."""
        self._client.close()
        return False

    @_scp_session
    def put(self, local_path, remote_path, recursive, scp_client=None):
        """Send data via scp."""
        scp_client.put(
            local_path, remote_path=remote_path, recursive=recursive
        )

    @_scp_session
    def get(self, remote_path, local_path, recursive, scp_client=None):
        """Get data via scp."""
        scp_client.get(remote_path, local_path, recursive=recursive)

    def start_shell(self):
        """Start an interactive shell."""
        if platform.system() == "Windows":
            return shell.WindowsSSHShell(self._client.invoke_shell())
        else:
            return shell.PosixSSHShell(self._client.invoke_shell())

    def run_cmd(self, cmd, check=False, writeout=False):
        """Execute a command over SSH.

        :param cmd str: The shell command to execute over ssh.
        :param check bool: Raise when the cmd returns a non-zero exit code.
        :param writeout bool: Print the returned stdout/err to sys.stdout.
        """
        # closure handles optional printing stdout/err and optional
        # exception raising if the remote command's exit code is non-zero.
        def _check_print_out(ssh_chan_output, check, writeout):
            if writeout:
                for out_fd in ssh_chan_output:
                    while out_fd.readable():
                        buf = out_fd.readline()
                        if not buf:
                            break
                        print(buf, end="")

            if check:
                _, stdout, stderr = ssh_chan_output
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0:
                    msg = "Remote command returned a non-zero exit code."
                    if stderr.readable():
                        buf = stderr.read().decode()
                        if buf:
                            msg = "{}".format(buf)
                    raise SSHCallError(msg, code=exit_status)

        try:
            cmd_output = self._client.exec_command(cmd, timeout=300)
        except paramiko.SSHException as ssh_error:
            raise IOError(
                "The command `{}` failed to execute, "
                "the error was: {}".format(cmd, ssh_error)
            )
        else:
            _check_print_out(cmd_output, check, writeout)
            return cmd_output

    def _connect(self, retry_limit=3, retry_interval_s=5):
        config = paramiko.SSHConfig()
        conf_path = pathlib.Path().home() / ".ssh" / "config"

        if conf_path.exists():
            config.parse(conf_path.open())
            cdict = config.lookup(self.device.hostname)
        else:
            cdict = None

        # There are often "SSH Protocol Banner" timeouts while waiting for the
        # server to present us with its SSH protocol banner.
        # We set paramiko's `banner_timeout` parameter, but that rarely solves
        # the problem. Therefore we retry the connection `retry_limit` times
        # to try and decrease the rate of failure.
        for _ in range(retry_limit):
            try:
                self._client.connect(
                    self.device.address,
                    username=self.device.username,
                    password=self.device.password
                    if self.device.password
                    else None,
                    key_filename=cdict["identityfile"] if cdict else None,
                    banner_timeout=60,
                )
            except paramiko.SSHException:
                time.sleep(retry_interval_s)
                continue
            else:
                break


class SCPValidationFailed(Exception):
    """SCP transfer md5 validation failed."""


class SSHCallError(Exception):
    """SSH remote command failed."""

    def __init__(self, *args, code=None, **kwargs):
        """Initialise the exception with a return_code attribute."""
        self.return_code = code
        super().__init__(*args, **kwargs)
