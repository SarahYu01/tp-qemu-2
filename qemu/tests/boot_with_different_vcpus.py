import logging
import time

from avocado.utils import process
from virttest import error_context


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU 'boot with 1/2/4/8/16 vcpus' test
    This is a sample QEMU test, so people can get used to some of the test APIs.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.

    error_context.context("Get the main VM", logging.info)
    vm = env.get_vm(params["main_vm"])

    vcpu_count = int(params.get("vcpu_count"))

    if vcpu_count:
        params["smp"] = vcpu_count
    else:
        test.fail("Couldn't get vcpu_count parameter")

    vm.create(params=params)
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    session.cmd('cat /proc/cpuinfo')

    vm.verify_status("running")

    vm.destroy()
    session.close()

