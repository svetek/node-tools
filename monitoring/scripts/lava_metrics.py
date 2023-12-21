#! /usr/bin/python3

import argparse
import json
import os

class MetricsCollector():
    def __init__(self, container, moniker, directory):
        self.container = container
        self.moniker = moniker
        self.directory = directory
        self.preffix = f'{moniker}_' if moniker else moniker

    def get_provider_update_info(self):
        metrics=["# HELP Lava provider update info. 1 - requires update; 0 - doesn't.",
                "# TYPE lava_provider_update_info gauge"]
        command_cv = f"docker exec {self.container} bash -c 'lavap version'"
        command_lv = f"docker exec {self.container} bash -c 'lavap query protocol params -o json'"
        cv=os.popen(command_cv).read().strip()
        lv=json.loads(os.popen(command_lv).read())["params"]["version"]["provider_target"]
        is_update = 1 if cv.strip() != lv.strip() else 0
        moniker_label = f', moniker="{self.moniker}"' if self.moniker else ''
        metrics.append(f'lava_provider_update_info{{current_version="{cv}", last_version="{lv}"{moniker_label}}} {is_update}')
        self.write_metrics_to_file(metrics, 'lava_provider_update_info')

    def get_chain_status(self):
        metrics=['# HELP Lava provider chain status.', '# TYPE lava_provider_chain_status gauge']
        statuses  = ['provider', 'frozen', 'unstaked']
        command = f"docker exec {self.container} bash -c 'lavap query pairing account-info --from $KEY -o json'"
        output = json.loads(os.popen(command).read())
        for status in statuses:
            if len(output[status]) > 0:
                for item in output[status]:
                    metric=f'lava_provider_chain_status{{chainID="{item["chain"]}", moniker="{item["moniker"]}", status="{status}"}} 1'
                    metrics.append(metric)
        self.write_metrics_to_file(metrics, 'lava_provider_chain_status')

    def write_metrics_to_file(self, metrics, metric_name):
        file_path=os.path.join(self.directory, f'{self.preffix}{metric_name}.prom')
        with open(file_path, 'w', encoding='utf-8') as f:
            for line in metrics:
                f.write(f'{line}\n')

    def get_metrics(self):
        self.get_provider_update_info()
        self.get_chain_status()

if  __name__ == "__main__":
    parser = argparse.ArgumentParser(
        usage='%(prog)s container [options]',
        description='The script allows you to collect lava metrics and write them to a file.')
    parser.add_argument('container', type=str, nargs='?', help='docker container name')
    parser.add_argument('-m', dest='moniker', nargs='?', default='', type=str, help='provider moniker')
    parser.add_argument('-d', dest='directory', nargs='?', default='/opt/monitoring/test', type=str, help='metrics file storage directory (default: /tmp)')
    args = parser.parse_args()
    MetricsCollector(args.container,
                     args.moniker,
                     args.directory).get_metrics()
