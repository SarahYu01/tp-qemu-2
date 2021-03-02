import logging
import re
import os
import time

from avocado.utils import astring
from avocado.utils import process

from virttest import error_context
from virttest import utils_test
from virttest import remote
from virttest import utils_net
from virttest import utils_misc
from virttest import utils_netperf
from virttest import env_process
from virttest import data_dir
from virttest.staging import utils_memory
from virttest.utils_numeric import normalize_data_size


@error_context.context_aware
def run(test, params, env):
    """
    Netperf testing, this case will:
    1) Get VM smp param.
    2) Modify VM smp param.
    3) Start the VM.
    4) VM cpu pin.
    5) VM vhost thread pin.
    6) Start netperf server.
    7) Start netperf clienr.
    8) Run netperf test.
    9) Finish test and clean up.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """


    error_context.context("Starting VM!", logging.info)
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])

    # modify vm's cpu count                                                                                                                                                                   
    vcpu_count = int(params.get("vcpu_count"))                                                                                                                                                
    if vcpu_count:                                                                                                                                                                            
        params["smp"] = vcpu_count                                                                                                                                                            
    else:                                                                                                                                                                                     
        test.fail("Couldn't get vcpu_count parameter")                                                                                                                                        
                                                                                                                                                                                              
    # create vm                                                                                                                                                                               
    vm.create(params=params)                                                                                                                         
    vm.verify_alive() 

    vm.verify_dmesg()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    # cpu pinning for better performance
    thread_list = []
    thread_list.extend(vm.vcpu_threads)
    host_numa_nodes = utils_misc.NumaInfo()

    vthread_num = 0
    for numa_node_id in host_numa_nodes.nodes:
        numa_node = host_numa_nodes.nodes[numa_node_id]
        for _ in range(len(numa_node.cpus)):
            if vthread_num >= len(thread_list):
                break
            vcpu_tid = thread_list[vthread_num]
            logging.debug("pin vcpu/vhost thread(%s) to cpu(%s)" %
                          (vcpu_tid, numa_node.pin_cpu(vcpu_tid)))
            vthread_num += 1

    # vhost pinning for better performance
    logging.debug("finding vhost pid ...")
    vhost_info = process.getoutput("ps aux | grep vhost")
    logging.debug(vhost_info)
    vhost_pid = re.findall("root\s+(\d+)\s+", vhost_info)
    logging.debug(vhost_pid)
    logging.debug("pin vhost thread(%s) to cpu(%s)" % (vhost_pid[1], 3))
    logging.debug(process.getoutput("taskset -cp 3 %s" % vhost_pid[1]))

    # netperf test
    # get params for netperf server 
    s_info = {}
    s_info["ip"] = params.get("server_ip")
    if s_info["ip"] is None:
        test.fail("Failed to get server ip")

    s_info["shell_client"] = params.get("shell_client", "ssh")
    s_info["shell_port"] = params.get("shell_port", "22")
    s_info["username"] = params.get("server_username", "root")
    s_info["password"] = params.get("server_password")
    if s_info["password"] is None:
        test.fail("Failed to get server password")

    s_info["shell_prompt"] = params.get("shell_prompt", r"^\[.*\][\#\$]\s*$")
    s_info["linesep"] = params.get("linesep", "\n")
    s_info["status_test_command"] = params.get("status_test_command", "echo $?")
    server_path = params.get("server_path")
    if server_path is None:
        test.fail("Failed to get server_path")

    compile_option_server = params.get("compile_option_server", "")

    # get netperf tar ball
    md5sum = params.get("md5sum", "")
    netperf_link = params.get("netperf_link")
    if netperf_link is None:
        test.fail("Failed to get netperf_link")

    netperf_link = os.path.join(data_dir.get_deps_dir("netperf"), netperf_link)

    # remote login netperf server and compile netperf
    netperf_server = utils_netperf.NetperfServer(s_info["ip"],
                                                 server_path,
                                                 md5sum, netperf_link,
                                                 client=s_info["shell_client"],
                                                 port=s_info["shell_port"],
                                                 username=s_info["username"],
                                                 password=s_info["password"],
                                                 prompt=s_info["shell_prompt"],
                                                 linesep=s_info["linesep"],
                                                 status_test_command=s_info["status_test_command"],
                                                 compile_option=compile_option_server)

    # get params for netperf client
    c_info = {}
    session.cmd("service iptables stop; iptables -F", ignore_all_errors=True)
    if params.get("netperf_vlan_test", "no") == "yes":
        vlan_nic = params.get("vlan_nic")
        client_ip = utils_net.get_linux_ipaddr(session, vlan_nic)[0]
    else:
        client_ip = vm.get_address()

    c_info["ip"] = client_ip
    c_info["shell_client"] = params.get("shell_client", "ssh")
    c_info["shell_port"] = params.get("shell_port", "22")
    c_info["username"] = params.get("client_username", "root")
    c_info["password"] = params.get("client_password")
    if s_info["password"] is None:
        test.fail("Failed to get client password")

    c_info["shell_prompt"] = params.get("shell_prompt", r"^\[.*\][\#\$]\s*$")
    c_info["linesep"] = params.get("linesep", "\n")
    c_info["status_test_command"] = params.get("status_test_command", "echo $?")
    client_path = params.get("client_path")
    if client_path is None:
        test.fail("Failed to get client_path")

    compile_option_client = params.get("compile_option_client", "")

    # remote login netperf client and compile netperf
    netperf_client = utils_netperf.NetperfClient(c_info["ip"],
                                                 client_path,
                                                 md5sum, netperf_link,
                                                 client=c_info["shell_client"],
                                                 port=c_info["shell_port"],
                                                 username=c_info["username"],
                                                 password=c_info["password"],
                                                 prompt=c_info["shell_prompt"],
                                                 linesep=c_info["linesep"],
                                                 status_test_command=c_info["status_test_command"],
                                                 compile_option=compile_option_client)

    # start netperf test
    try:
	    # start netperf server
        netperf_server.start()

        # start netperf client
        netperf_test_duration = int(params.get("netperf_test_duration", 60))
        netperf_para_sess = params.get("netperf_para_sessions", "1")
        test_protocols = params.get("test_protocols", "TCP_STREAM")
        netperf_cmd_prefix = params.get("netperf_cmd_prefix", "")
        netperf_output_unit = params.get("netperf_output_unit", " ")
        netperf_package_sizes = params.get("netperf_package_sizes")
        test_option = params.get("test_option", "")

        test_option += " -l %s" % netperf_test_duration
        if params.get("netperf_remote_cpu") == "yes":
            test_option += " -C"
        if params.get("netperf_local_cpu") == "yes":
            test_option += " -c"
        if netperf_output_unit in "GMKgmk":
            test_option += " -f %s" % netperf_output_unit
        for protocol in test_protocols.split():
            error_context.context("Testing %s protocol" % protocol, logging.info)
            test_option += " -t %s" % protocol

        logging.info(netperf_client.start(s_info["ip"], test_option))
        time.sleep(5)

    # clean up
    finally:
        netperf_server.stop()
        netperf_server.package.env_cleanup(True)
        netperf_client.package.env_cleanup(True)

        vm.verify_status("running")
        vm.destroy()
        session.close()

