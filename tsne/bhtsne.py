#!/usr/bin/env python

'''
A simple Python wrapper for the bh_tsne binary that makes it easier to use it
for TSV files in a pipeline without any shell script trickery.

Note: The script does some minimal sanity checking of the input, but don't
    expect it to cover all cases. After all, it is a just a wrapper.

Example:

    > echo -e '1.0\t0.0\n0.0\t1.0' | ./bhtsne.py -d 2 -p 0.1
    -2458.83181442  -6525.87718385
    2458.83181442   6525.87718385

The output will not be normalised, maybe the below one-liner is of interest?:

    python -c 'import numpy;  from sys import stdin, stdout; 
        d = numpy.loadtxt(stdin); d -= d.min(axis=0); d /= d.max(axis=0);
        numpy.savetxt(stdout, d, fmt="%.8f", delimiter="\t")'

Authors:     Pontus Stenetorp    <pontus stenetorp se>
             Philippe Remy       <github: philipperemy>
Version:    2016-03-08
'''

# Copyright (c) 2013, Pontus Stenetorp <pontus stenetorp se>
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
import sys
import os
current_dir = os.path.dirname(os.path.realpath(__file__)) + '/'
sys.path.append(current_dir + '..')

import gzip
import pickle
from argparse import ArgumentParser, FileType
from matplotlib.markers import TICKUP
from os.path import abspath, dirname, isfile, join as path_join
from shutil import rmtree
from struct import calcsize, pack, unpack
from subprocess import Popen
from sys import stderr, stdin, stdout
from tempfile import mkdtemp
from platform import system
from os import devnull
import numpy as np
import matplotlib.pyplot as plt
import utils

### Constants
IS_WINDOWS = True if system() == 'Windows' else False
BH_TSNE_BIN_PATH = path_join(dirname(__file__), 'windows', 'bh_tsne.exe') if IS_WINDOWS else path_join(dirname(__file__), 'bh_tsne')
assert isfile(BH_TSNE_BIN_PATH), ('Unable to find the bh_tsne binary in the '
    'same directory as this script, have you forgotten to compile it?: {}'
    ).format(BH_TSNE_BIN_PATH)
# Default hyper-parameter values from van der Maaten (2014)
# https://lvdmaaten.github.io/publications/papers/JMLR_2014.pdf (Experimental Setup, page 13)
DEFAULT_NO_DIMS = 2
INITIAL_DIMENSIONS = 50
DEFAULT_PERPLEXITY = 50
DEFAULT_THETA = 0.5
EMPTY_SEED = -1

###

def _argparse():
    argparse = ArgumentParser('bh_tsne Python wrapper')
    argparse.add_argument('-d', '--no_dims', type=int,
                          default=DEFAULT_NO_DIMS)
    argparse.add_argument('-p', '--perplexity', type=float,
            default=DEFAULT_PERPLEXITY)
    # 0.0 for theta is equivalent to vanilla t-SNE
    argparse.add_argument('-t', '--theta', type=float, default=DEFAULT_THETA)
    argparse.add_argument('-r', '--randseed', type=int, default=EMPTY_SEED)
    argparse.add_argument('-n', '--initial_dims', type=int, default=INITIAL_DIMENSIONS)
    argparse.add_argument('-v', '--verbose', action='store_true')
    argparse.add_argument('-i', '--input', type=FileType('r'), default=stdin)
    argparse.add_argument('-o', '--output', type=FileType('w'),
            default=stdout)
    return argparse


class TmpDir:
    def __enter__(self):
        self._tmp_dir_path = mkdtemp()
        return self._tmp_dir_path

    def __exit__(self, type, value, traceback):
        rmtree(self._tmp_dir_path)


def _read_unpack(fmt, fh):
    return unpack(fmt, fh.read(calcsize(fmt)))

def bh_tsne(samples, no_dims=DEFAULT_NO_DIMS, initial_dims=INITIAL_DIMENSIONS, perplexity=DEFAULT_PERPLEXITY,
            theta=DEFAULT_THETA, randseed=EMPTY_SEED, verbose=False):

    samples -= np.mean(samples, axis=0)
    print samples.shape
    cov_x = np.cov(samples, rowvar=0)
    print cov_x.shape
    [eig_val, eig_vec] = np.linalg.eig(cov_x)
    print eig_vec.shape

    # sorting the eigen-values in the descending order
    eig_vec = eig_vec[:, eig_val.argsort()[::-1]]

    if initial_dims > len(eig_vec):
        initial_dims = len(eig_vec)

    # truncating the eigen-vectors matrix to keep the most important vectors
    eig_vec = eig_vec[:, :initial_dims]
    samples = np.dot(samples, eig_vec)

    # Assume that the dimensionality of the first sample is representative for
    #   the whole batch
    sample_dim = len(samples[0])
    sample_count = len(samples)

    print "calculate tsne"

    # bh_tsne works with fixed input and output paths, give it a temporary
    #   directory to work in so we don't clutter the filesystem
    with TmpDir() as tmp_dir_path:
        # Note: The binary format used by bh_tsne is roughly the same as for
        #   vanilla tsne
        with open(path_join(tmp_dir_path, 'data.dat'), 'wb') as data_file:
            # Write the bh_tsne header
            data_file.write(pack('iiddi', sample_count, sample_dim, theta, perplexity, no_dims))
            # Then write the data
            for sample in samples:
                data_file.write(pack('{}d'.format(len(sample)), *sample))
            # Write random seed if specified
            if randseed != EMPTY_SEED:
                data_file.write(pack('i', randseed))

        # Call bh_tsne and let it do its thing
        with open(devnull, 'w') as dev_null:
            bh_tsne_p = Popen((abspath(BH_TSNE_BIN_PATH), ), cwd=tmp_dir_path,
                    # bh_tsne is very noisy on stdout, tell it to use stderr
                    #   if it is to print any output
                    stdout=stderr if verbose else dev_null)
            bh_tsne_p.wait()
            assert not bh_tsne_p.returncode, ('ERROR: Call to bh_tsne exited '
                    'with a non-zero return code exit status, please ' +
                    ('enable verbose mode and ' if not verbose else '') +
                    'refer to the bh_tsne output for further details')

        # Read and pass on the results
        with open(path_join(tmp_dir_path, 'result.dat'), 'rb') as output_file:
            # The first two integers are just the number of samples and the
            #   dimensionality
            result_samples, result_dims = _read_unpack('ii', output_file)
            # Collect the results, but they may be out of order
            results = [_read_unpack('{}d'.format(result_dims), output_file)
                for _ in xrange(result_samples)]
            # Now collect the landmark data so that we can return the data in
            #   the order it arrived
            results = [(_read_unpack('i', output_file), e) for e in results]
            # Put the results in order and yield it
            results.sort()
            for _, result in results:
                yield result
            # The last piece of data is the cost for each sample, we ignore it
            #read_unpack('{}d'.format(sample_count), output_file)

def problem_29(args, n):
    argp = _argparse().parse_args(args[1:])

    train_set, valid_set, test_set = utils.load_MNIST(current_dir + "../mnist.pkl.gz")

    data = np.asarray(np.vstack((train_set[0], valid_set[0], test_set[0])), dtype=np.float64)
    y = np.hstack((train_set[1], valid_set[1], test_set[1]))
    data = data[:n]
    y = y[:n]
    X_2d = np.zeros((n, 2))

    print "loaded data"

    k = 0
    for result in bh_tsne(data, no_dims=argp.no_dims, perplexity=argp.perplexity, theta=argp.theta, randseed=argp.randseed,
            verbose=argp.verbose, initial_dims=argp.initial_dims):
        X_2d[k,:] = result
        k+=1
    

    plt.figure(figsize=(120, 120))
    plt.axis('off')
    X_2d *= 100
    
    c = ['b', 'g', 'r', 'y','#12efff','#eee111','#123456','#abc222','#000999','#32efff']
    for i in xrange(10):
        plt.scatter(X_2d[(y == i) , 0], X_2d[(y == i), 1], label=str(i), marker='$'+str(i)+'$', s=18)

    plt.savefig("figure5_"+str(n)+".svg", format="svg")


def problem_28(args, data, n, name, fig_size=50):
    argp = _argparse().parse_args(args[1:])

    datax, datay = data
    datax = datax[:n]
    datay = datay[:n]
    X_2d = np.zeros((n, 2))

    print "loaded data"

    k = 0
    for result in bh_tsne(datax, no_dims=argp.no_dims, perplexity=argp.perplexity, theta=argp.theta, randseed=argp.randseed,
            verbose=argp.verbose, initial_dims=argp.initial_dims):
        X_2d[k,:] = result
        k+=1

    plt.figure(figsize=(fig_size, fig_size))
    plt.axis('off')
    X_2d *= 100
    
    plt.scatter(X_2d[:, 0], X_2d[:, 1], c=datay, edgecolor=None)

    plt.savefig(name+".svg", format="svg")


if __name__ == '__main__':
    from sys import argv
    trainx, trainy, testx, testy = utils.load_cifar(current_dir + "../cifar-10-batches-py/")
    trainx = np.asarray(np.vstack((trainx, testx)), dtype=np.float64)
    trainy = np.hstack((trainy, testy))

    problem_28(argv, (trainx, trainy), trainx.shape[0], "cifar")
    problem_29(argv, 70000)

    ##### SCIKIT NEEDED FOR NEWSDATA ######
    # from sklearn.datasets import fetch_20newsgroups
    # data = fetch_20newsgroups(shuffle=True, random_state=1337)
    # from sklearn.feature_extraction.text import TfidfVectorizer
    # X_train_tf = TfidfVectorizer(use_idf=True,  max_features=1500, dtype=np.float64).fit_transform(data.data).toarray()
    # print X_train_tf.shape
    # problem_28(argv, (X_train_tf, data.target), X_train_tf.shape[0], "newsdata", fig_size=20)
    ##### SCIKIT NEEDED FOR NEWSDATA ######
