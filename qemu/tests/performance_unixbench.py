import logging
import re
import os

from avocado.utils import astring
from avocado.utils import process

from virttest import error_context
from virttest import utils_test
from virttest import remote
from virttest import utils_net
from virttest import utils_misc
from virttest import env_process
from virttest import data_dir
from virttest.staging import utils_memory
from virttest.utils_numeric import normalize_data_size


def get_host_numa_node():
    """
    Get host NUMA node whose node size is not zero
    """
    host_numa = utils_memory.numa_nodes()
    node_list = []
    numa_info = process.getoutput("numactl -H")
    for i in host_numa:
        node_size = re.findall(r"node %d size: \d+ \w" % i, numa_info)[0].split()[-2]
        if node_size != '0':
            node_list.append(str(i))
    return node_list


@error_context.context_aware
def run(test, params, env):
    """
    [Memory][Numa] NUMA memdev option, this case will:
    1) Check host's numa node(s).
    2) Modify VM smp param
    3) Start the VM.
    4) VM cpu pin
    5) Run unixbench test.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error_context.context("Check host's numa node(s)!", logging.info)
    valid_nodes = get_host_numa_node()
    if len(valid_nodes) < 2:
        test.cancel("The host numa nodes that whose size is not zero should be "
                    "at least 2! But there is %d." % len(valid_nodes))
    node1 = valid_nodes[0]
    node2 = valid_nodes[1]

    if params.get('policy_mem') != 'default':
        error_context.context("Assign host's numa node(s)!", logging.info)
        params['host-nodes_mem0'] = node1
        params['host-nodes_mem1'] = node2

    if params.get('set_node_hugepage') == 'yes':
        hugepage_size = utils_memory.get_huge_page_size()
        normalize_total_hg1 = int(normalize_data_size(params['size_mem0'], 'K'))
        hugepage_num1 = normalize_total_hg1 // hugepage_size
        if 'numa_hugepage' in params['shortname']:
            params['target_nodes'] = "%s %s" % (node1, node2)
            normalize_total_hg2 = int(normalize_data_size(params['size_mem1'], 'K'))
            hugepage_num2 = normalize_total_hg2 // hugepage_size
            params['target_num_node%s' % node2] = hugepage_num2
        else:
            params['target_nodes'] = node1
        params['target_num_node%s' % node1] = hugepage_num1
        params['setup_hugepages'] = 'yes'
        env_process.preprocess(test, params, env)

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

    # download unixbench tar ball
    session.cmd_status_output('uname -a')
    os_type = params["os_type"]

    tmp_dir = params.get("tmp_dir", "/tmp/")
    unixbench_deps_dir = data_dir.get_deps_dir("unixbench")
    unixbench_file = params.get('unixbench_file')
    unixbench_remote_path = os.path.join(unixbench_deps_dir, unixbench_file)
    unixbench_path = params.get('unixbench_path', tmp_dir)
    unixbench_src_path = os.path.join(unixbench_path, unixbench_file)

    vm.copy_files_to(unixbench_remote_path, unixbench_path)

    src_path = unixbench_src_path
    dst_path = tmp_dir
    unixbench_version = params.get('unixbench_version')
    unixbench = params.get('unixbench')
    unixbench_source_path = os.path.join(dst_path, unixbench)

    # compile unixbench
    compile_cmd = params["linux_compile_cmd"] % (src_path, dst_path, unixbench_source_path)
    logging.info("Compiling %s in guest..." % unixbench)
    status, output = session.cmd_status_output(compile_cmd)
    if status != 0:
        test.fail("Failed to compile unixbench with error: %s" % output)
    logging.debug(output)

    # run unixbench test
    test_cmd = params.get("test_cmd")
    status, output = session.cmd_status_output("cd %s; %s " % (unixbench_source_path, test_cmd), timeout=3000)
    if status != 0:
        test.fail("Failed to run unixbench with error: %s" % output)
    logging.debug(output)

    vm.verify_status("running")

    vm.destroy()                                                                                                                                                                                                                                                                                                         
    session.close()

