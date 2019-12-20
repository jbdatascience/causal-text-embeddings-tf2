# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Run masked LM/next sentence masked_lm pre-training for BERT in tf2.0."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import functools

from absl import app
from absl import flags
from absl import logging
import tensorflow as tf

# pylint: disable=unused-import,g-import-not-at-top,redefined-outer-name,reimported
from modeling import model_training_utils
from nlp import bert_modeling as modeling
from nlp import bert_models
from nlp import optimization
from nlp.bert import common_flags
from nlp.bert import input_pipeline
from nlp.bert import model_saving_utils
from utils.misc import tpu_lib

flags.DEFINE_string('input_files', None,
                    'File path to retrieve training data for pre-training.')
# Model training specific flags.
flags.DEFINE_integer(
    'max_seq_length', 128,
    'The maximum total input sequence length after WordPiece tokenization. '
    'Sequences longer than this will be truncated, and sequences shorter '
    'than this will be padded.')
flags.DEFINE_integer('max_predictions_per_seq', 20,
                     'Maximum predictions per sequence_output.')
flags.DEFINE_integer('train_batch_size', 32, 'Total batch size for training.')
flags.DEFINE_integer('num_steps_per_epoch', 1000,
                     'Total number of training steps to run per epoch.')
flags.DEFINE_float('warmup_steps', 10000,
                   'Warmup steps for Adam weight decay optimizer.')

common_flags.define_common_bert_flags()

FLAGS = flags.FLAGS


def get_pretrain_input_data(input_file_pattern, seq_length,
                            max_predictions_per_seq, batch_size, strategy):
    """Returns input dataset from input file string."""

    # When using TPU pods, we need to clone dataset across
    # workers and need to pass in function that returns the dataset rather
    # than passing dataset instance itself.
    use_dataset_fn = isinstance(strategy, tf.distribute.experimental.TPUStrategy)
    if use_dataset_fn:
        if batch_size % strategy.num_replicas_in_sync != 0:
            raise ValueError(
                'Batch size must be divisible by number of replicas : {}'.format(
                    strategy.num_replicas_in_sync))

        # As auto rebatching is not supported in
        # `experimental_distribute_datasets_from_function()` API, which is
        # required when cloning dataset to multiple workers in eager mode,
        # we use per-replica batch size.
        batch_size = int(batch_size / strategy.num_replicas_in_sync)

    def _dataset_fn(ctx=None):
        """Returns tf.data.Dataset for distributed BERT pretraining."""
        input_files = []
        for input_pattern in input_file_pattern.split(','):
            input_files.extend(tf.io.gfile.glob(input_pattern))

        train_dataset = input_pipeline.create_pretrain_dataset(
            input_files,
            seq_length,
            max_predictions_per_seq,
            batch_size,
            is_training=True,
            input_pipeline_context=ctx)
        return train_dataset

    return _dataset_fn if use_dataset_fn else _dataset_fn()


def main(_):
    # Users should always run this script under TF 2.x
    assert tf.version.VERSION.startswith('2.')

    if not FLAGS.model_dir:
        FLAGS.model_dir = '/tmp/bert20/'
    strategy = None
    if FLAGS.strategy_type == 'mirror':
        strategy = tf.distribute.MirroredStrategy()
    elif FLAGS.strategy_type == 'tpu':
        cluster_resolver = tpu_lib.tpu_initialize(FLAGS.tpu)
        strategy = tf.distribute.experimental.TPUStrategy(cluster_resolver)
    else:
        raise ValueError('The distribution strategy type is not supported: %s' %
                         FLAGS.strategy_type)

    # train_input_fn is a fn that takes no arguments
    train_input_fn = functools.partial(get_pretrain_input_data, FLAGS.input_files,
                                       FLAGS.max_seq_length, FLAGS.max_predictions_per_seq,
                                       FLAGS.train_batch_size, strategy)

    dataset = train_input_fn()
    print(dataset.element_spec)

    for val in dataset.take(1):
        print(val)

    pass


if __name__ == '__main__':
    app.run(main)