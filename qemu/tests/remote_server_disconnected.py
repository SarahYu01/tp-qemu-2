import os
import netaddr
import logging

from avocado.utils import process


def run(test, params, env):
    """
    Convert remote image.

    1) Start VM
    2) Disconnect local host from the remote server one by one,
       make sure the vm can be accessed.
    """

    def _check_hosts(hosts):
        if len(hosts) < 2:
            test.cancel("2 remote servers at least are required.")
        for h in hosts:
            if os.path.exists(h) or netaddr.valid_ipv6(h):
                test.cancel("Neither ipv6 nor unix domain"
                            " socket is supported by now.")

    hosts = []
    if params.get("enable_gluster") == "yes":
        hosts.append(params["gluster_server"])
        hosts.extend(params.get("gluster_peers", "").split())

    _check_hosts(hosts)
    hosts.pop()  # The last server should be accessible

    disconn_cmd = params["disconn_cmd"]
    recover_cmd = params["recover_cmd"]
    conn_check_cmd = params["conn_check_cmd"]
    disk_op_cmd = params["disk_op_cmd"]
    disk_op_tm = int(params["disk_op_timeout"])

    session = None
    disconn_hosts = []
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    tm = int(params.get("login_timeout", 300))
    session = vm.wait_for_login(timeout=tm)

    try:
        for host in hosts:
            logging.info("Disconnect to %s" % host)
            process.system(disconn_cmd.format(source=host),
                           ignore_status=True, shell=True)
            if process.system(conn_check_cmd.format(source=host),
                              ignore_status=True, shell=True) == 0:
                test.error("Failed to disconnect to remote server")
            disconn_hosts.append(host)

            logging.info("Do disk I/O in VM")
            s, o = session.cmd_status_output(disk_op_cmd, timeout=disk_op_tm)
            if s != 0:
                test.fail("Failed to do I/O in VM: %s" % o)
    finally:
        for host in disconn_hosts:
            logging.info("Recover connection to %s" % host)
            process.system(recover_cmd.format(source=host),
                           ignore_status=True, shell=True)
            if process.system(conn_check_cmd.format(source=host),
                              ignore_status=True, shell=True) != 0:
                logging.warn("Failed to recover connection to %s" % host)
        if session:
            session.close()
        vm.destroy()
