import logging
import time
import random

import aexpect

from virttest import utils_test
from virttest import utils_net
from virttest import utils_misc


def run(test, params, env):
    """
    Nic bonding test in guest.

    1) Start guest with four nic devices.
    2) Setup bond0 in guest.
    3) Execute file transfer test between guest and host.
    4) Repeatedly put down/up interfaces by 'ip link'
    5) Execute file transfer test between guest and host.

    :param test: Kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    timeout = int(params.get("login_timeout", 1200))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    ifnames = utils_net.get_linux_ifname(session_serial)

    ssh_login_cmd = (
        "echo LoginGraceTime 5m  >> /etc/ssh/sshd_config &&"
        " systemctl restart sshd.service || service sshd restart")
    session_serial.cmd_output_safe(ssh_login_cmd)

    # get params of bonding
    nm_stop_cmd = "service NetworkManager stop; true"
    session_serial.cmd_output_safe(nm_stop_cmd)
    modprobe_cmd = "modprobe bonding"
    bonding_params = params.get("bonding_params")
    if bonding_params:
        modprobe_cmd += " %s" % bonding_params
    session_serial.cmd_output_safe(modprobe_cmd)
    session_serial.cmd_output_safe("ifconfig bond0 up")
    setup_cmd = "ifenslave bond0 " + " ".join(ifnames)
    session_serial.cmd_output_safe(setup_cmd)
    # do a pgrep to check if dhclient has already been running
    pgrep_cmd = "pgrep dhclient"
    try:
        session_serial.cmd_output_safe(pgrep_cmd)
    # if dhclient is there, killl it
    except aexpect.ShellCmdError:
        logging.info("it's safe to run dhclient now")
    else:
        logging.info("dhclient is already running, kill it")
        session_serial.cmd_output_safe("killall -9 dhclient")
        time.sleep(1)

    session_serial.cmd_output_safe("dhclient bond0")

    # get_bonding_nic_mac and ip
    try:
        link_set_cmd = "ip link set dev %s %s"
        logging.info("Test file transferring:")
        utils_test.run_file_transfer(test, params, env)

        logging.info("Failover test with file transfer")
        transfer_thread = utils_misc.InterruptedThread(
            utils_test.run_file_transfer, (test, params, env))
        transfer_thread.start()
        try:
            while transfer_thread.isAlive():
                for ifname in ifnames:
                    session_serial.cmd(link_set_cmd % (ifname, "down"))
                    time.sleep(random.randint(1, 30))
                    session_serial.cmd(link_set_cmd % (ifname, "up"))
                    time.sleep(random.randint(1, 30))

        except Exception:
            transfer_thread.join(suppress_exception=True)
            raise
        else:
            transfer_thread.join()

        logging.info("Failover test 2 with file transfer")
        transfer_thread = utils_misc.InterruptedThread(
            utils_test.run_file_transfer, (test, params, env))
        transfer_thread.start()
        try:
            nic_num = len(ifnames)
            up_index = 0
            while transfer_thread.isAlive():
                up_index = up_index % nic_num
                for num in range(nic_num):
                    if num == up_index:
                        session_serial.cmd(link_set_cmd % (ifnames[num], "up"))
                    else:
                        session_serial.cmd(link_set_cmd % (ifnames[num], "down"))
                time.sleep(random.randint(1, 5))
                up_index += 1
        except Exception:
            transfer_thread.join(suppress_exception=True)
            raise
        else:
            transfer_thread.join()
    finally:
        session_serial.sendline("ifenslave -d bond0 " + " ".join(ifnames))
        session_serial.sendline("kill -9 `pgrep dhclient`")
        session_serial.sendline("sed -i '$ d' /etc/ssh/sshd_config")
