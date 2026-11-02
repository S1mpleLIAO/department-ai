"""Run the native four-user workload against the integrated scheduler."""
import asyncio
import assistant_capacity_four_probe as probe
from assistant_integrated_pool import IntegratedPool
probe.NonblockingProbePool=IntegratedPool
probe.RESULT_PATH=probe.STATE/"assistant-capacity-integrated-results.json"
probe.result["mode"]="integrated Manager, 4 containers, synthetic streaming/tool workload"
if __name__=="__main__":asyncio.run(probe.main())
