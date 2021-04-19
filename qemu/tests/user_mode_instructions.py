import os
import re
import shutil
import logging

from aexpect import ShellCmdError
from avocado.utils import process

from virttest import data_dir
from virttest import utils_net
from virttest import utils_misc
from virttest import error_context
from virttest import utils_package


@error_context.context_aware
def run(test, params, env):
    """
    user_mode instructions test.

    1) Boot up VM
    2) Prepare the test environment
    3) Execute tests, analyze the result
    4) Finish test

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    os_type = params["os_type"]
    login_timeout = int(params.get("login_timeout", 360))

    tmp_dir = params.get("tmp_dir", "/tmp/")
    kvm_testcase_deps_dir = data_dir.get_deps_dir("kvm-testcase")
    kvm_testcase_file = params.get('kvm_testcase_file')
    kvm_testcase_remote_path = os.path.join(kvm_testcase_deps_dir, kvm_testcase_file)
    kvm_testcase_path = params.get('kvm_testcase_path', tmp_dir)
    kvm_testcase_src_path = os.path.join(kvm_testcase_path, kvm_testcase_file)

    # Get host cpuinfo
    cmd = "cat /proc/cpuinfo | grep processor | wc -l"
    error_context.context("Get cpuinfo by command '%s'"
                          % cmd, logging.info)
    status, output = utils_misc.cmd_status_output(cmd, shell=True)
    vcpu_count = output

    # create vm
    vm = env.get_vm(params["main_vm"])
    params["smp"] = vcpu_count

    vm.create(params=params)
    vm.verify_alive()

    #serial_session = vm.wait_for_serial_login(timeout=login_timeout)
    guest_session = vm.wait_for_login(timeout=login_timeout)

    vm.copy_files_to(kvm_testcase_remote_path, kvm_testcase_path)

    src_path = kvm_testcase_src_path
    dst_path = tmp_dir
    kvm_testcase_version = params.get('kvm_testcase_version')
    kvm_testcase_source_path = os.path.join(dst_path, kvm_testcase_version)

    compile_cmd = params["linux_compile_cmd"] % (src_path, dst_path, kvm_testcase_source_path)
    logging.info("Compiling %s in guest..." % kvm_testcase_version)
    guest_session.cmd(compile_cmd)

    hugepage = params.get("hugepage")
    if hugepage == "yes":
        hugepage_setup = params.get("hugepage_setup")
        hugepage_verify = params.get("hugepage_verify")
        guest_session.cmd(hugepage_setup)
        guest_session.cmd(hugepage_verify)

    test_cmd = params.get("test_cmd")
    guest_session.cmd("cd %s; %s " % (kvm_testcase_source_path, test_cmd), timeout=3000)


    guest_session.close()
    #serial_session.close()
