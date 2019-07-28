#!/usr/bin/env python3

# AIPlanner - Deep Learning Financial Planner
# Copyright (C) 2018-2019 Gordon Irlam
#
# All rights reserved. This program may not be used, copied, modified,
# or redistributed without permission.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE.

from argparse import ArgumentParser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from json import dumps, loads
from math import exp
from os import chmod, environ, listdir, makedirs, rmdir, scandir, stat, statvfs
from os.path import expanduser
from random import choice, randrange, uniform
from re import match
from shlex import quote
from shutil import rmtree
from socketserver import ThreadingMixIn
from subprocess import PIPE, Popen
from tempfile import mkdtemp
from threading import BoundedSemaphore, Thread
from time import sleep, time
from traceback import print_tb

from gym_fin.common.scenario_space import allowed_gammas
from gym_fin.envs.model_params import load_params_file

from spia import YieldCurve

def report_exception(args, e):

    with open(expanduser(args.root_dir) + '/server.log', 'a') as f:

        print('----------------------------------------', file = f)
        print_tb(e.__traceback__, file = f)
        print(e.__class__.__name__ + ': ' + str(e), file = f)
        print('----------------------------------------', file = f)

class InferEvaluateDaemon:

    def __init__(self, args, *, evaluate, gammas, log, priority = 0):

        self.args = args
        self.log = log

        models_dir = expanduser(self.args.models_dir)
        cmd = [
            environ['AIPLANNER_HOME'] + '/ai/eval_model.py',
            '--daemon',
            '--nice', str(priority),
            '--eval-no-warn',
            '--eval-no-display-returns',
            '--models-dir', models_dir,
            '--train-seeds', str(self.args.train_seeds),
            '--ensemble',
            ('--' if evaluate else '--no-') + 'evaluate',
            ('--' if self.args.warm_cache else '--no-') + 'warm-cache',
            '-c', models_dir + '/base-scenario.txt',
            '--eval-num-timesteps', str(self.args.eval_num_timesteps),
            '--num-environment', str(self.args.num_environments),
            '--num-trace-episodes', str(self.args.num_trace_episodes),
            '--pdf-buckets', str(self.args.pdf_buckets),
        ]
        for gamma in gammas:
            cmd += ['--gamma', str(gamma)]
        self.proc = Popen(cmd, stdin = PIPE, stdout = PIPE, stderr = self.log)

    def infer_evaluate(self, api_data, *, options = [], prefix = ''):

        makedirs(self.args.results_dir, exist_ok = True)
        dir = mkdtemp(prefix = prefix, dir = self.args.results_dir)
        chmod(dir, 0o755)

        try:

            aid = dir[len(self.args.results_dir) + 1:]
            data = dumps(api_data).encode('utf-8')

            options = list(options) + [
                '--aid', quote(aid),
                '--result-dir', quote(dir),
                '--api-content-length', str(len(data)),
            ]
            options = ' '.join(options) + '\n'

            self.proc.stdin.write(options.encode('utf-8') + data)
            self.proc.stdin.flush()

            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise IOError
                string = line.decode('utf-8')
                if string == 'AIPlanner-Result\n':
                    line = self.proc.stdout.readline()
                    line = line.rstrip().decode('utf-8')
                    attr, val = line.split(':')
                    assert attr == 'Content-Length'
                    length = int(val)
                    data = self.proc.stdout.read(length)
                    return aid, data
                elif string != '\n':
                    self.log.write(line)
                    self.log.flush()

        except IOError as e:

            return aid, '{"error": "No evaluator."}\n'.encode('utf-8')

        finally:

            # Delete if empty.
            try:
                rmdir(dir + '/seed_all')
                rmdir(dir)
            except:
                pass

class ApiHTTPServer(ThreadingMixIn, HTTPServer):

    def __init__(self, args, log):

        super().__init__((args.host, args.port), RequestHandler)
        self.args = args
        self.log =  log

        if self.args.infer:
            self.infer_run_lock = BoundedSemaphore(self.args.num_concurrent_infer_jobs)
            self.infer_daemon = [
                InferEvaluateDaemon(self.args, evaluate = False, gammas = self.args.gamma, log = self.log, priority = 10)
                    for _ in range(self.args.num_concurrent_infer_jobs)
            ]

        if self.args.evaluate:
            self.evaluate_run_lock = BoundedSemaphore(self.args.num_concurrent_evaluate_jobs)
            self.evaluate_daemons = {
                gamma: [InferEvaluateDaemon(self.args, evaluate = True, gammas = [gamma], log = self.log) for _ in range(self.args.num_concurrent_evaluate_jobs)]
                    for gamma in self.args.gamma
            }

class RequestHandler(BaseHTTPRequestHandler):

    def send_result(self, result_bytes, mime_type, headers = []):

        self.send_response(200)
        self.send_header('Content-Type', mime_type)
        self.send_header('Content-Length', len(result_bytes))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(result_bytes)

    def do_POST(self):

        try:

            if self.path.startswith('/api/'):

                content_type = self.headers.get('Content-Type')
                content_length = self.headers.get('Content-Length')
                if content_length == None:
                    self.send_error(411) # Length Required
                    return
                content_length = int(content_length)
                if not 0 <= content_length <= 100e6:
                    self.send_error(413) # Payload Too Large
                    return

                data = self.rfile.read(content_length)
                try:
                    request = loads(data.decode('utf-8'))
                except ValueError:
                    self.send_error(400) # Bad Request
                    return

                data = None
                headers = []
                if self.path == '/api/infer':

                    if self.server.args.infer:
                        data = self.run_models(request, evaluate = False)
                    else:
                        self.send_error(403) # Forbidden
                        return

                elif self.path == '/api/evaluate':

                    if self.server.args.evaluate:
                        data = self.run_models(request, evaluate = True)
                    else:
                        self.send_error(403) # Forbidden

                elif self.path == '/api/subscribe':

                    result = self.subscribe(request)
                    data = (dumps(result, indent = 4, sort_keys = True) + '\n').encode('utf-8')

                if data != None:
                    self.send_result(data, 'application/json', headers = headers)
                    return

            self.send_error(404) # Not Found

        except Exception as e:

            report_exception(self.server.args, e)
            self.send_error(500) # Internal Server Error

    def do_GET(self):

        try:

            data = None
            headers = []
            if self.path == '/healthcheck':

                if self.healthcheck():
                    data = 'OK\n'
                else:
                    data = 'FAIL\n'

                data, filetype = data.encode('utf-8'), 'text/plain'
                headers.append(('Cache-Control', 'no-cache'))

            elif self.path.startswith('/api/data/'):

                m  = match('^/api/data/(.+?)(/(.+))?$', self.path)
                if not m:
                    self.send_error(404) # Not Found
                    return
                data, filetype = self.get_file(m[1], m[3])

            elif self.path == '/api/market':

                data = self.market()
                print(data)
                data['real_short_rate'] = exp(data['real_short_rate']) - 1
                data['nominal_short_rate'] = exp(data['nominal_short_rate']) - 1
                data, filetype = (dumps(data, indent = 4, sort_keys = True) + '\n').encode('utf-8'), 'application/json'
                headers.append(('Cache-Control', 'max-age=3600'))

            if data != None:

                self.send_result(data, filetype, headers = headers)
                return

            self.send_error(404) # Not Found

        except Exception as e:

            report_exception(self.server.args, e)
            self.send_error(500) # Internal Server Error

    def get_file(self, aid, name):

        if name:
            filename = 'aiplanner-' + name
        else:
            filename = 'aiplanner.json'
        path = aid + '/seed_all/' + filename

        print(path)
        filetype = None
        if '..' not in path:
            if filename.endswith('.json'):
                filetype = 'application/json'
            elif filename.endswith('.csv'):
                filetype = 'text/csv'
            elif filename.endswith('.svg'):
                filetype = 'image/svg+xml'

        data = None
        if filetype:
            try:
                data = open(self.server.args.results_dir + '/' + path, 'rb').read()
            except IOError:
                pass

        if data == None:
            filetype = None

        return data, filetype

    def healthcheck(self):

        api_data = [{
            'cid': 'healthcheck',

            'sex': choice(('male', 'female')),
            'sex2': choice(('male', 'female', None)),
            'age': uniform(20, 80),
            'age2': uniform(20, 80),
            'life_expectancy_additional': uniform(-5, 10),
            'life_expectancy_additional2': uniform(-5, 10),

            'age_retirement': uniform(50, 80),
            'income_preretirement': uniform(20000, 200000),
            'income_preretirement2': uniform(20000, 200000),
            'consume_preretirement': uniform(15000, 100000),
            'have_401k': choice((True, False)),
            'have_401k2': choice((True, False)),

            'guaranteed_income': [{
                'type': choice(('social_security', 'income_annuity')),
                'owner': choice(('self', 'spouse')),
                'start': uniform(50, 80),
                'final': uniform(80, 150),
                'payout': uniform(10000, 100000),
                'inflation_adjustment': 0.02,
                'joint': choice((True, False)),
                'payout_fraction': uniform(0, 1),
                'source_of_funds': choice(('taxable', 'tax_deferred', 'tax_free')),
                'exclusion_period': uniform(0, 20),
                'exclusion_amount': uniform(5000, 10000),
            } for _ in range(randrange(5))],

            'p_tax_deferred': uniform(10000, 1000000),
            'p_tax_free': uniform(10000, 1000000),
            'p_taxable_bonds': uniform(10000, 1000000),
            'p_taxable_stocks': uniform(10000, 1000000),
            'p_taxable_stocks_basis': uniform(10000, 1000000),

            'stocks_price': uniform(0.5, 2),
            'nominal_short_rate': uniform(-0.01, 0.1),
            'inflation_short_rate': uniform(-0.01, 0.1),

            'spias': choice((True, False)),

            'rra': [choice(self.server.args.gamma)],

            'num_evaluate_timesteps': self.server.args.eval_num_timesteps_healthcheck,
        }]

        if self.server.args.infer:
            data = self.run_models(api_data, evaluate = False, prefix = 'healthcheck-')
            result = loads(data.decode('utf-8'))
            if result['error'] or result['result'][0][0]['error']:
                self.server.log.write(data)
                self.server.log.flush()
                return False

        if self.server.args.evaluate:
            data = self.run_models(api_data, evaluate = True, prefix = 'healthcheck-')
            result = loads(data.decode('utf-8'))
            if result['error'] or result['result'][0][0]['error']:
                self.server.log.write(data)
                self.server.log.flush()
                return False

        return True

    def market(self):

        market_file = load_params_file(expanduser(self.server.args.models_dir) + '/market-data.txt')

        now = datetime.utcnow().date().isoformat()
        real_short_rate = YieldCurve('real', now, permit_stale_days = 7).spot(0)
        nominal_short_rate = YieldCurve('nominal', now, permit_stale_days = 7).spot(0)

        return {
            'stocks_price': market_file['stocks_price'],
            'stocks_volatility': market_file['stocks_volatility'],
            'real_short_rate': real_short_rate,
            'nominal_short_rate': nominal_short_rate,
        }

    def run_models(self, api_data, *, evaluate, options = [], prefix = ''):

        if evaluate:
            lock = self.server.evaluate_run_lock
            timeout = 60
                # Development client resubmits request after 120 seconds, so keep timeout plus evaluation time below that.
        else:
            lock = self.server.infer_run_lock
            timeout = None

        market = self.market()
        for api_scenario in api_data:
            if not 'stocks_volatility' in api_scenario:
                api_scenario['stocks_volatility'] = market['stocks_volatility']
            if sum(x in api_scenario for x in ['real_short_rate', 'nominal_short_rate', 'inflation_short_rate']) < 2:
                if not 'real_short_rate' in api_scenario:
                    api_scenario['real_short_rate'] = exp(market['real_short_rate']) - 1
                if sum(x in api_scenario for x in ['real_short_rate', 'nominal_short_rate', 'inflation_short_rate']) < 2:
                    api_scenario['nominal_short_rate'] = exp(market['nominal_short_rate']) - 1

        if lock.acquire(timeout = timeout):
            try:
                if evaluate:
                    results = self.run_evaluate(api_data, options = options, prefix = prefix)
                    data = (dumps(results, sort_keys = True) + '\n').encode('utf-8')
                else:
                    aid, data = self.run_model(self.server.infer_daemon, api_data, options = options, prefix = prefix)
                return data
            finally:
                lock.release()
        else:
            self.send_error(503, 'Overloaded: try again later')

    def run_evaluate(self, api_data, *, options = [], prefix = ''):

        if len(api_data) == 0:
            return {'error': None, 'result': []}
        elif len(api_data) > 1:
            return {'error': 'Multiple scenarios to evaluate.'}
        gammas = api_data[0].get('rra')
        if gammas == None:
            gammas = self.server.args.gamma
        if len(gammas) != len(set(gammas)):
            return {'error': 'Duplicate gamma values.'}
        for gamma in gammas:
            if not gamma in self.server.evaluate_daemons.keys():
                return {'error': 'Unsupported gamma value: ' + str(gamma)}
        eval_num_timesteps = api_data[0].get('num_evaluate_timesteps')
        if not isinstance(eval_num_timesteps, (int, float)):
            eval_num_timesteps = self.server.args.eval_num_timesteps
        if not 0 <= eval_num_timesteps <= self.server.args.eval_num_timesteps_max:
            return {'error': 'num_evalate_timeteps out of range.'}
        num_trace_episodes = api_data[0].get('num_sample_paths')
        if not isinstance(num_trace_episodes, (int, float)):
            num_trace_episodes = self.server.args.num_trace_episodes
        if not 0 <= num_trace_episodes <= self.server.args.num_trace_episodes_max:
            return {'error': 'num_sample_paths out of range.'}
        options += [
            '--eval-num-timesteps', str(eval_num_timesteps),
            '--num-trace-episodes', str(num_trace_episodes),
        ]
        results = [None] * len(gammas)
        threads = []
        error_result = None
        def run(i, gamma):
            try:
                my_api_data = [dict(api_data[0], rra = [gamma])]
                aid, data = self.run_model(self.server.evaluate_daemons[gamma], my_api_data, options = options, prefix = prefix)
                result = loads(data.decode('utf-8'))
                if result['error']:
                    results[i] = result
                else:
                    results[i] = result['result'][0][0]
            except Exception as e:
                results[i] = {'error': e.__class__.__name__ + ': ' + (str(e) or 'Exception encountered.')}
            finally:
                results[i]['aid'] = aid
                results[i]['cid'] = my_api_data[0].get('cid')
        for i, gamma in enumerate(gammas):
            thread = Thread(target = run, args = (i, gamma), daemon = False)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        return {
            'error': None,
            'result': [results],
        }

    def run_model(self, daemon_queue, api_data, *, options = [], prefix = ''):

        try:
            daemon = daemon_queue.pop()
            return daemon.infer_evaluate(api_data, options = options, prefix = prefix)
        finally:
            daemon_queue.append(daemon)

    def subscribe(self, request):

        email = request.get('email', '')
        email = email.strip()
        print(email)
        if not match('^\S+@\S+\.\S+$', email):
            return {'error': 'Invalid email address.'}

        try:
            with open(expanduser(self.server.args.root_dir) + '/subscribe.txt', 'a') as f:
                f.write(email + '\n')
        except IOError:
            raise

        cmd = ['/usr/sbin/sendmail',
            '-f', 'root',
            self.server.args.admin_email,
        ]
        mta = Popen(cmd, stdin = PIPE, encoding = 'utf-8')

        header = 'From: "' + self.server.args.notify_name + '" <' + self.server.args.notify_email + '''>
To: ''' + self.server.args.admin_email + '''
Subject: ''' + self.server.args.project_name + ': subscribe' + '''

'''
        body = email + '\n'

        mta.stdin.write(header + body)
        mta.stdin.close()

        if mta.wait() != 0:
            self.send_error(500) # Internal Server Error
            return

        return {
            'error': None,
            'result': None,
        }

class PurgeQueueServer:

    def __init__(self, args):

        self.args = args

    def serve_forever(self):

        while True:
            try:
                self.purgeq()
                sleep(self.args.purge_frequency)
            except Exception as e:
                report_exception(self.args, e)
                sleep(10)

    def purgeq(self):

        entries = list(scandir(self.args.results_dir))
        entries.sort(key = lambda entry: entry.stat(follow_symlinks = False).st_mtime)

        for entry in entries:

            age = time() - entry.stat(follow_symlinks = False).st_mtime

            if age <= self.args.purge_keep_time:
                break

            dir = self.args.results_dir + '/' + entry.name
            s = statvfs(self.args.results_dir)
            free = float(s.f_bavail) / s.f_blocks
            ifree = float(s.f_favail) / s.f_files

            try:
                stat(dir + '/failures.json')
                purge_time = self.args.purge_time_failure
            except IOError:
                if entry.name.startswith('healthcheck-'):
                    purge_time = self.args.purge_time_healthcheck
                else:
                    purge_time = self.args.purge_time_success

            if free < self.args.purge_keep_free or ifree < self.args.purge_keep_free or age >= purge_time:
                def rmfail(function, path, excinfo):
                    print('Error purging file:', path)
                assert dir.startswith(expanduser(self.args.root_dir))
                assert dir.startswith(self.args.results_dir)
                rmtree(dir, onerror = rmfail)

def boolean_flag(parser, name, default = False):

    under_dest = name.replace('-', '_')
    parser.add_argument('--' + name, action = "store_true", default = default, dest = under_dest)
    parser.add_argument('--' + 'no-' + name, action = "store_false", dest = under_dest)

def main():

    parser = ArgumentParser()

    # Generic options.
    parser.add_argument('--serve', action = 'append', default = [], choices=('http', 'purgeq'))
    parser.add_argument('--root-dir', default = '~/aiplanner-data')

    # HTTP options.
    parser.add_argument('--host', default = 'localhost')
    parser.add_argument('--port', type = int, default = 3000)
    boolean_flag(parser, 'infer', default = True) # Support /api/infer.
    boolean_flag(parser, 'evaluate', default = True) # Support /api/evaluate.
    boolean_flag(parser, 'warm-cache', default = True) # Pre-load tensorflow/Rllib models.
    parser.add_argument('--num-concurrent-infer-jobs', type = int, default = 2) # Each job may have multiple scenarios with multiple gamma values.
    parser.add_argument('--num-concurrent-evaluate-jobs', type = int, default = 1) # Each job is a single scenario with multiple gamma values.
    parser.add_argument('--gamma', action = 'append', type = float, default = []) # Supported gamma values.
    parser.add_argument('--train-seeds', type = int, default = 10)
    parser.add_argument('--models-dir', default = '~/aiplanner-data/models')
    parser.add_argument('--eval-num-timesteps', type = int, default = 50000)
    parser.add_argument('--eval-num-timesteps-healthcheck', type = int, default = 1000)
    parser.add_argument('--eval-num-timesteps-max', type = int, default = 100000)
    parser.add_argument('--num-environments', type = int, default = 10) # Number of parallel environments to use for a single model evaluation. Speeds up tensorflow.
    parser.add_argument('--num-trace-episodes', type = int, default = 5) # Default number of sample traces to generate.
    parser.add_argument('--num-trace-episodes-max', type = int, default = 10000)
    parser.add_argument('--pdf-buckets', type = int, default = 20) # Number of non de minus buckets to use in computing consume probability density distribution.

    # HTTP subscribe options.
    parser.add_argument('--notify-email', default = 'notify@aiplanner.com')
    parser.add_argument('--notify-name', default = 'AIPlanner Notify')
    parser.add_argument('--admin-email', default = 'admin@aiplanner.com')
    parser.add_argument('--project-name', default = 'AIPlanner')

    # purgeq options.
    parser.add_argument('--purge-frequency', type = int, default = 3600) # Purge the resultsdirectory of old files every this many seconds.
    parser.add_argument('--purge-keep-free', type = float, default = 0.02) # Keep this much proportion of disk space/inodes free.
    parser.add_argument('--purge-keep-time', type = int, default = 3600) # Keep directories around for this long regardless.
    parser.add_argument('--purge-time-failure', type = int, default = 90 * 86400) # Delete failed scenarios after this long.
    parser.add_argument('--purge-time-healthcheck', type = int, default = 3600) # Delete healthcheck scenarios after this long.
    parser.add_argument('--purge-time-success', type = int, default = 86400) # Delete successful scenarios after this long.

    args = parser.parse_args()
    root_dir = expanduser(args.root_dir)
    args.results_dir = root_dir + '/results'
    if not args.gamma:
        args.gamma = allowed_gammas

    makedirs(args.results_dir, exist_ok = True)

    if not args.serve or 'http' in args.serve:
        log = open(expanduser(args.root_dir) + '/server.log', 'ab')
        server = ApiHTTPServer(args, log)
        Thread(target = server.serve_forever, daemon = True).start()

    if not args.serve or 'purgeq' in args.serve:
        server = PurgeQueueServer(args)
        Thread(target = server.serve_forever, daemon = True).start()

    try:
        while True:
            sleep(86400)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
