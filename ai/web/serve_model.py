#!/usr/bin/env python3

# AIPlanner - Deep Learning Financial Planner
# Copyright (C) 2018 Gordon Irlam
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
from os import chmod, listdir, makedirs, remove, scandir
from os.path import expanduser, isdir
from re import match
from socketserver import ThreadingMixIn
from subprocess import PIPE, Popen
from tempfile import mkdtemp
from threading import BoundedSemaphore, Lock, Thread
from time import sleep
from traceback import print_tb

from gym_fin.envs.model_params import dump_params_file, load_params_file

class ApiHTTPServer(ThreadingMixIn, HTTPServer):

    def __init__(self, args):

        super().__init__((args.host, args.port), RequestHandler)
        self.args = args
        self.run_lock = BoundedSemaphore(self.args.num_concurrent_jobs)

class RequestHandler(BaseHTTPRequestHandler):

    def do_POST(self):

        if self.path in ('/api/scenario', '/api/result', '/api/full'):

            content_type = self.headers.get('Content-Type')
            content_length = int(self.headers['Content-Length'])
            data = self.rfile.read(content_length)
            json_data = data.decode('utf-8')
            request = loads(json_data)

            if self.path == '/api/scenario':
                result = self.run_models_with_lock(request)
            elif self.path == '/api/result':
                result = self.get_results(request)
            elif self.path == '/api/full':
                result = self.run_full(request)
            else:
                assert False

            if result:

                result_bytes = dumps(result).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(result_bytes))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(result_bytes)

            return

        self.send_error(404)

    def do_GET(self):

        if self.path.startswith('/api/data/'):

            asset = self.path[len('/api/data/'):];
            if '..' not in asset:
                if asset.endswith('.png'):
                    filetype = 'image/png'
                elif asset.endswith('.svg'):
                    filetype = 'image/svg+xml'
                else:
                    filetype = None
                if filetype:
                    path = self.server.args.results_dir + '/' + asset
                    try:
                        data = open(path, 'rb').read()
                    except IOError:
                        pass
                    else:
                        self.send_response(200)
                        self.send_header('Content-Type', filetype)
                        self.send_header('Content-Length', len(data))
                        self.send_header('Connection', 'close')
                        self.end_headers()
                        self.wfile.write(data)
                        return

        self.send_error(404)

    def run_models_with_lock(self, request):

        if self.server.run_lock.acquire(timeout = 60):
            # Development client resubmits request after 120 seconds, so keep timeout plus evaluation time below that.
            try:
                dir = self.save_params(request)
                model_prefix = self.get_model_prefix(dir)
                model_runner = ModelRunner(dir, self.server.args)
                model_runner.eval_models('prelim', model_prefix)
                return {'id': dir[len(self.server.args.results_dir) + 1:]}
            finally:
                self.server.run_lock.release()
        else:
            self.send_error(503, 'Overloaded: try again later')

    def save_params(self, request):

        dir = mkdtemp(prefix = '', dir = self.server.args.results_dir)
        chmod(dir, 0o755)

        dump_params_file(dir + '/aiplanner-request.txt', request, prefix = '')

        request_params = dict(request)
        request_params['defined_benefits'] = dumps(request_params['defined_benefits'])
        try:
            request_params['p_taxable_stocks_basis_fraction'] = request_params['p_taxable_stocks_basis'] / request_params['p_taxable_stocks']
        except ZeroDivisionError:
            request_params['p_taxable_stocks_basis_fraction'] = 0
        del request_params['p_taxable_stocks_basis']
        request_params['income_preretirement_age_end'] = request_params['age_retirement']
        for param in ('p_taxable_real_bonds', 'p_taxable_iid_bonds', 'p_taxable_bills'):
            request_params[param] = 0
        request_params['p_taxable_nominal_bonds'] = request_params['p_taxable_bonds']
        del request_params['p_taxable_bonds']
        request_params['nominal_spias'] = request_params['spias']
        del request_params['spias']
        request_params['consume_clip'] = 0
        request_params['consume_income_ratio_max'] = float('inf')
        request_params['display_returns'] = False

        dump_params_file(dir + '/aiplanner-scenario.txt', request_params)

        return dir

    def get_model_prefix(self, dir):

        request = load_params_file(dir + '/aiplanner-request.txt', prefix = '')

        unit = 'single' if request['sex2'] == None else 'couple'
        spias = 'spias' if request['spias'] else 'no_spias'
        suffix = '' if self.server.args.modelset_suffix == None else '-' + self.server.args.modelset_suffix
        model_prefix = self.server.args.modelset_dir + 'aiplanner.' + unit + '-' + spias + suffix

        return model_prefix

    def get_results(self, request):

        id = request['id']
        assert match('[A-Za-z0-9_]+$', id)
        mode = request['mode']
        assert mode in ('prelim', 'full')

        dir = self.server.args.results_dir + '/' + id + '/' + mode

        best_ce = float('-inf')
        model_seed = 0
        while True:

            dir_seed = dir + '/' + str(model_seed)

            if not isdir(dir_seed):
                break

            try:
                final = loads(open(dir_seed + '/aiplanner-final.json').read())
            except IOError:
                return {'error': 'Results not found.'}

            if final['error'] != None:
                return final

            initial = loads(open(dir_seed + '/aiplanner-initial.json').read())

            results = dict(initial, **final)
            results['data_dir'] = '/api/data/' + dir_seed[len(self.server.args.results_dir) + 1:]

            if results['ce'] > best_ce:
                best_ce = results['ce']
                best_results = results

            model_seed += 1

        if model_seed == 0:
            return {'error': 'Results not found.'}
        else:
            return best_results

    def run_full(self, request):

        email = request['email']
        assert match('[^\s]+@[^\s]+$', email)
        name = request['name']
        assert match('.*$', name)
        id = request['id']
        assert match('[A-Za-z0-9_]+$', id)

        dir = self.server.args.results_dir + '/' + id
        dump_params_file(dir + '/aiplanner-request-full.txt', request, prefix = '')

        open(self.server.args.run_queue + '/' + id, 'w')
        #symlink('../' + id, self.server.args.run_queue + '/' + id)

        run_queue_length = len(listdir(self.server.args.run_queue))

        return {'run_queue_length': run_queue_length}

class ModelRunner(object):

    def __init__(self, dir, args):

        self.dir = dir
        self.args = args

    def eval_models(self, mode, model_prefix):

        processes = []
        for model_seed in range(self.args.num_models):
            processes.append(self.eval_model(mode, model_prefix, model_seed))

        fail = False
        for process in processes:
            if process.wait() != 0:
                fail = True

        if fail:
            raise Exception('Model evaluation failed mode ' + mode + ': ' + self.dir)

    def train_eval_models(self):

        dir_model = self.dir + '/models'
        model_prefix = dir_model + '/aiplanner'

        makedirs(dir_model, exist_ok = True)

        unit = self.get_family_unit()
        num_timesteps = str(self.args.train_single_num_timesteps) if unit == 'single' else str(self.args.train_couple_num_timesteps)

        processes = []
        for model_seed in range(self.args.num_models):
            processes.append(self.train_model(model_prefix, model_seed, num_timesteps))

        fail = False
        for process in processes:
            if process.wait() != 0:
                fail = True

        if fail:
            raise Exception('Model training failed: ' + self.dir)

        mode = 'full'
        self.eval_models(mode, model_prefix)

    def get_family_unit(self):

        request = load_params_file(self.dir + '/aiplanner-request.txt', prefix = '')

        unit = 'single' if request['sex2'] == None else 'couple'

        return unit

    def eval_model(self, mode, model_prefix, model_seed):

        model_dir = model_prefix + '-seed_' + str(model_seed) + '.tf'
        dir_seed = self.dir + '/' + mode + '/' + str(model_seed)

        makedirs(dir_seed, exist_ok = True)

        num_timesteps = str(self.args.eval_prelim_num_timesteps) if mode == 'prelim' else str(self.args.eval_full_num_timesteps)

        return Popen(('./eval_model',
            '--result-dir', dir_seed,
            '--model-dir', model_dir,
            '-c', model_dir + '/assets.extra/params.txt',
            '-c', '../market_data.txt',
            '-c', self.dir + '/aiplanner-scenario.txt',
            '--eval-num-timesteps', num_timesteps,
            '--num-trace-episodes', str(self.args.num_trace_episodes),
            '--num-environments', str(self.args.num_environments),
            '--pdf-buckets', str(self.args.pdf_buckets),
        ))

    def train_model(self, model_prefix, model_seed, num_timesteps):

        model_dir = model_prefix + '-seed_' + str(model_seed) + '.tf'

        return Popen(('./train_model',
            '--model-dir', model_dir,
            '-c', '../aiplanner-scenario.txt',
            '-c', '../market_data.txt',
            '-c', self.dir + '/aiplanner-scenario.txt',
            '--train-seed', str(model_seed),
            '--train-num-timesteps', num_timesteps,
        ))

class RunQueueServer(object):

    def __init__(self, args):

        self.args = args

        self.run_queue_lock = Lock()
        self.output_lock = Lock()

        self.running = {}

    def report_exception(self, e):

        self.output_lock.acquire()
        print('----------------------------------------')
        print_tb(e.__traceback__)
        print(e.__class__.__name__ + ': ' + str(e))
        print('----------------------------------------')
        self.output_lock.release()

    def serve_forever(self):

        prev_pending = None
        while True:
            try:
                run_queue_length = 0
                oldest_id = None
                oldest_age = float('inf')
                self.run_queue_lock.acquire()
                with scandir(self.args.run_queue) as iter:
                    for entry in iter:
                        run_queue_length += 1
                        if len(self.running) < self.args.num_concurrent_jobs:
                            age = entry.stat(follow_symlinks = False).st_mtime
                            if age < oldest_age and entry.name not in self.running:
                                oldest_id = entry.name
                                oldest_age = age
                self.run_queue_lock.release()
                if oldest_id:
                    id = oldest_id
                    thread = Thread(target = self.serve_thread, args = (id, ), daemon = True)
                    self.log('Starting', id)
                    self.running[id] = thread
                    thread.start()
                else:
                    pending = max(0, run_queue_length - len(self.running))
                    if pending != prev_pending:
                        prev_pending = pending
                        if pending > 0:
                            self.log('Jobs pending', pending)
                    sleep(10)
            except Exception as e:
                self.report_exception(e)
                sleep(10)
            except KeyboardInterrupt:
                break

    def log(self, *args):

        self.output_lock.acquire()
        print(datetime.now().replace(microsecond = 0).isoformat(), *args)
        self.output_lock.release()

    def serve_thread(self, id):

        try:
            self.serve_one(id)
            self.log('Completed', id)
        except Exception as e:
            self.report_exception(e)
            self.log('Failed', id)
        finally:
            try:
                self.run_queue_lock.acquire()
                remove(self.args.run_queue + '/' + id)
                del self.running[id]
            except Exception as e:
                self.report_exception(e)
                pass
            finally:
                self.run_queue_lock.release()

    def serve_one(self, id):

        dir = self.args.results_dir + '/' + id
        request = load_params_file(dir + '/aiplanner-request-full.txt', prefix = '')
        email = request['email']
        name = request['name']

        try:
            dir = self.args.results_dir + '/' + id
            model_runner = ModelRunner(dir, self.args)
            model_runner.train_eval_models()
            self.notify(email, name, id, True)
        except Exception as e:
            self.notify(email, name, id, False)
            raise e

    def notify(self, email, name, id, success):

        cmd = ['/usr/sbin/sendmail',
            '-f', 'root',
            email,
        ]
        if not success:
            cmd.append(self.args.admin_email)
        mta = Popen(cmd, stdin = PIPE, encoding = 'utf-8')

        header = 'From: "' + self.args.notify_name + '" <' + self.args.notify_email + '''>
To: ''' + email + '''
Subject: ''' + self.args.project_name + ': ' + name + '''

'''

        if success:
            body = 'Your requested ' + self.args.project_name + ' results are now available at ' + self.args.base_url + 'result/' + id + '''

Thank you for using ''' + self.args.project_name + '''.
'''
        else:
            body = 'Something went wrong computing your ' + self.args.project_name + ''' results. We are looking into the problem.

JobRef: ''' + id + '''
'''

        mta.stdin.write(header + body)
        mta.stdin.close()

        assert mta.wait() == 0

def main():

    parser = ArgumentParser()

    # Generic options.
    parser.add_argument('--serve', default='http', choices=('http', 'runq'))
    parser.add_argument('--root-dir', default = '~/aiplanner-data')
    parser.add_argument('--num-concurrent-jobs', type = int, default = 1) # Each job represents the concurrent execution of num_models models in a single scenario.
    parser.add_argument('--num-models', type = int, default = 10)
    parser.add_argument('--num-trace-episodes', type = int, default = 5) # Number of sample traces to generate.
    parser.add_argument('--num-environments', type = int, default = 10) # Number of parallel environments to use for a single model evaluation. Speeds up tensor flow.
    parser.add_argument('--pdf-buckets', type = int, default = 20) # Number of non de minus buckets to use in computing consume probability density distribution.

    # HTTP options.
    parser.add_argument('--host', default = 'localhost')
    parser.add_argument('--port', type = int, default = 3000)
    parser.add_argument('--modelset-dir', default = './')
    parser.add_argument('--modelset-suffix')
    parser.add_argument('--eval-prelim-num-timesteps', type = int, default = 20000)

    # runq options.
    parser.add_argument('--notify-email', default = 'notify@aiplanner.com')
    parser.add_argument('--notify-name', default = 'AIPlanner')
    parser.add_argument('--admin-email', default = 'admin@aiplanner.com')
    parser.add_argument('--project-name', default = 'AIPlanner')
    parser.add_argument('--base-url', default = 'https://www.aiplanner.com/')
    parser.add_argument('--train-single-num-timesteps', type = int, default = 1000000)
    parser.add_argument('--train-couple-num-timesteps', type = int, default = 2000000)
    parser.add_argument('--eval-full-num-timesteps', type = int, default = 2000000)

    args = parser.parse_args()
    root_dir = expanduser(args.root_dir)
    args.results_dir = root_dir + '/results'
    args.run_queue = root_dir + '/runq'

    makedirs(args.results_dir, exist_ok = True)
    makedirs(args.run_queue, exist_ok = True)

    if args.serve == 'http':
        server = ApiHTTPServer(args)
    else:
        server = RunQueueServer(args)
    server.serve_forever()

if __name__ == '__main__':
    main()
