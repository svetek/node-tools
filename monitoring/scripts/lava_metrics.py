#! /usr/bin/python3

import argparse
import json
import os
import subprocess

class MetricsCollector:
    def __init__(self, container, network, moniker, directory):
        self.container = container
        self.network = network
        self.moniker = moniker
        self.directory = directory
        self.prefix = f'{moniker}_{network}-'

    def run_command(self, command):
        return subprocess.run(command, shell=True, capture_output=True, text=True).stdout.strip()

    def get_provider_update_info(self):
        metrics = ["# HELP Lava provider update info. 1 - requires update; 0 - doesn't.",
                   "# TYPE lava_provider_update_info gauge"]
        cv = self.run_command(f"docker exec {self.container} bash -c 'lavap version'")
        lv = json.loads(self.run_command(f"docker exec {self.container} bash -c 'lavap query protocol params -o json'"))["params"]["version"]["provider_target"]
        is_update = 1 if cv != lv else 0
        moniker_label = f', moniker="{self.moniker}"' if self.moniker else ''
        metrics.append(f'lava_provider_update_info{{current_version="{cv}", last_version="{lv}", network="{self.network}" {moniker_label}}} {is_update}')
        self.write_metrics_to_file(metrics, 'lava_provider_update_info')

    def get_chain_status(self):
        metrics = ['# HELP Lava provider chain status.', '# TYPE lava_provider_chain_status gauge']
        statuses = ['provider', 'frozen', 'unstaked']
        output = json.loads(self.run_command(f"docker exec {self.container} bash -c 'lavap query pairing account-info --from $WALLET -o json'"))
        for status in statuses:
            for item in output.get(status, []):
                metrics.append(f'lava_provider_chain_status{{network="{self.network}", moniker="{item.get("moniker", "")}", chainID="{item["chain"]}", status="{status}"}} 1')
        self.write_metrics_to_file(metrics, 'lava_provider_chain_status')

    def write_metrics_to_file(self, metrics, metric_name):
        file_path = os.path.join(self.directory, f'{self.prefix}{metric_name}.prom')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(f'{line}\n' for line in metrics)

    def get_metrics(self):
        self.get_provider_update_info()
        self.get_chain_status()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Collect lava metrics and write them to a file.')
    parser.add_argument('container', help='Docker container name')
    parser.add_argument('-m', '--moniker', default='', help='Provider moniker')
    parser.add_argument('-n', '--network', default='', help='Provider network')
    parser.add_argument('-d', '--directory', default='/opt/monitoring/test', help='Metrics file storage directory (default: /opt/monitoring/test)')
    args = parser.parse_args()

    MetricsCollector(args.container, args.network, args.moniker, args.directory).get_metrics()
