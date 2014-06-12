#!/usr/bin/python

import urllib2
import json
import time
import sys
import argparse

OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3

return_code = OK

options = {'hostname': '127.0.0.1',
           'port': '9615',
           'graphite_host': '',
           'graphite_port': '80',
           'warning': '200,30', # memory (MB), restarts (# per minute)
           'critical': '400,60'
          }

def check_defaults(args):
    for key in options.keys():
        if getattr(args, key) is not None:
            options[key] = getattr(args,key)

def get_args():
    parser = argparse.ArgumentParser(description='A Nagios plugin for checking the Node.js/pm2 process metrics of a remote host')
    parser.add_argument('-H', '--hostname', help='the pm2 host whose metrics to collect')
    parser.add_argument('-p', '--port', help='the port to connect to on the pm2 host')
    parser.add_argument('-G', '--graphite-host', help='the graphite host whose metrics to query')
    parser.add_argument('-P', '--graphite-port', help='the port on which graphite host is listening')
    parser.add_argument('-w', '--warning', help='warning levels')
    parser.add_argument('-c', '--critical', help='critical levels')
    return parser.parse_args()

def collect_metrics():
    try:
        response = urllib2.urlopen('http://%s:%s' % (options['hostname'], options['port']))
    except urllib2.URLError, e:
        print("UNKNOWN - Could not collect metrics via %s:%s" % (options['hostname'], options['port']))
        sys.exit(UNKNOWN)

    try:
        result = json.load(response)
    except ValueError, e:
        print("UNKNOWN - Connected to %s:%s but could not parse response as valid JSON." % (options['hostname'], options['port']))
        sys.exit(UNKNOWN)

    return result['processes']

def print_and_set_return_code(msg, code):
    global return_code
    print msg
    if return_code < code:
        return_code = code

def get_restarts_json():
    # grab the deriviate of restarts metric, i.e. the change in # of restarts since previous graphite metric
    #
    # look back 3+ minutes because 
    #   1) sometimes the most recent datapoint exists but hasn't yet been written to disk (i.e. it's value is null), and
    #   2) with the derivative function, the oldest datapoint retrieved is always null since we didn't request the metric value 
    #      before that, which we'd need to calculate derivative
    query = 'http://%s:%s/render?&target=derivative(diamond.%s.Pm2Collector.*.restarts)&format=json&from=-5minute' \
             % (options['graphite_host'], options['graphite_port'], options['hostname'].split('.')[0])
    try:
        response = urllib2.urlopen(query)
    except urllib2.URLError, e:
        print("UNKNOWN - Received no response from %s" % query)
        sys.exit(UNKNOWN)

    try:
        result = json.load(response)
    except ValueError, e:
        print("UNKNOWN - Unable to parse response from %s into JSON" % query)
        sys.exit(UNKNOWN)
    return result

def check_metrics(processes):
    recent_restarts = get_restarts_json()
    for proc in processes:
        # check restarts
        restart_data = [item['datapoints'] for item in recent_restarts if ("%s.restarts" % proc['name']) in item['target']]
        values = []
        if len(restart_data) > 0:
            values = [x[0] for x in restart_data[0] if x[0] is not None]
        if len(values) == 0:
            print_and_set_return_code("UNKNOWN - No recent data on the change in restarts for process %s" % proc['name'], UNKNOWN)
        else:
            max_restarts = max(values)
            if max_restarts > float(options['critical'].split(',')[1]):
                print max_restarts
                print_and_set_return_code("CRITICAL - process '%s' has recently restarted " 
                                          "%s times within a minute" \
                                          % (proc['name'], str(int(max_restarts))), CRITICAL)
            elif max_restarts > float(options['warning'].split(',')[1]):
                print_and_set_return_code("WARNING - process '%s' has recently restarted " 
                                          "%s times within a minute" \
                                          % (proc['name'], str(int(max_restarts))), WARNING)
            else:
                print_and_set_return_code("OK - process '%s' has recently restarted " 
                                          "%s times within a minute" \
                                          % (proc['name'], str(int(max_restarts))), OK)

        # check memory
        memory_usage = proc['monit']['memory'] / 1000. / 1000.
        if memory_usage > float(options['critical'].split(',')[0]):
            print_and_set_return_code("CRITICAL - process '%s' memory use is %f "
                                      "(> %s threshold)" % (proc['name'], memory_usage, options['critical'].split(',')[0]),
                                      CRITICAL)

        elif memory_usage > float(options['warning'].split(',')[0]):
            print_and_set_return_code("WARNING - process '%s' memory use is %f "
                                      "(> %s threshold)" % (proc['name'], memory_usage, options['warning'].split(',')[0]),
                                      WARNING)
        else:
            print "OK - process '%s' memory use is %f" % (proc['name'], memory_usage)

def main():
    check_defaults(get_args())
    pm2_processes = collect_metrics()
    check_metrics(pm2_processes)
    sys.exit(return_code)

if __name__ == '__main__':
    main()
