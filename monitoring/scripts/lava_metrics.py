#! /usr/bin/python3

import argparse
import json
import os

class MetricsCollector():
    def __init__(self, container):
        self.container = container
        self.metrics   = []

    def get_chain_status(self):
        self.metrics.append('# HELP Lava provider chain status.\n# TYPE lava_provider_chain_status gauge')
        statuses  = ['provider', 'frozen', 'unstaked']
        command = "docker exec %s bash -c 'lavap query pairing account-info --from $KEY -o json'" % self.container
        output = json.loads(os.popen(command).read())
        for status in statuses:
            if len(output[status]) > 0:
                for item in output[status]:
                    metric='lava_provider_chain_status{chainID="%s", moniker="%s", status="%s"} 1' % (item["chain"], item["moniker"], status)
                    self.metrics.append(metric)

    def get_metrics(self):
        self.get_chain_status()
        return self.metrics

if  __name__ == "__main__":
    parser = argparse.ArgumentParser(
        usage='%(prog)s container [options]',
        description='The script allows you to collect lava metrics and write them to a file.')
    parser.add_argument('container', type=str, help='docker container name')
    parser.add_argument('-d', dest='directory', nargs='?', default='/tmp', type=str, help='metrics file storage directory (default: /tmp)')
    parser.add_argument('-f', dest='file_name', nargs='?', default='metrics.prom', type=str, help='metrics file name *.prom (default: metrics.prom)')
    args = parser.parse_args()
    metrics=MetricsCollector(args.container).get_metrics()

    file_path=os.path.join(args.directory, args.file_name)
    with open(file_path, 'w', encoding='utf-8') as f:
        for line in metrics:
            f.write(f"{line}\n")
