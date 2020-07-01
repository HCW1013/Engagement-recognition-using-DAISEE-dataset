#!/usr/bin/env python
# coding: utf-8
import tensorflow as tf
import tensorflow.keras.layers as kl
import tensorflow.keras.losses as klo
from tensorflow.keras.applications.vgg16 import VGG16
from daisee_data_preprocessing import DataPreprocessing
import datetime
import os
from tqdm import tqdm

BATCH_SIZE = 64
LR = 0.005
EPOCHS = 1000
use_pretrained = True
pretrained_name = 'mobilenet'
current_time = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
checkpoint_dir = 'checkpoints/'
log_dir = 'logs/'
train_summary_writer = tf.summary.create_file_writer(log_dir)

# This part works for setting up space in gpu
gpus = tf.config.experimental.list_physical_devices('GPU')
if gpus:
    # Restrict TensorFlow to only allocate 1GB * 2 of memory on the first GPU
    try:
        tf.config.experimental.set_virtual_device_configuration(
            gpus[0],
            [tf.config.experimental.VirtualDeviceConfiguration(memory_limit=1024 * 2)])
        logical_gpus = tf.config.experimental.list_logical_devices('GPU')
        print(len(gpus), "Physical GPUs,", len(logical_gpus), "Logical GPUs")
    except RuntimeError as e:
        # Virtual devices must be set before GPUs have been initialized
        print(e)


def create_log_dir(log_dir, checkpoint_dir):
    if not os.path.exists(log_dir):
        os.mkdir(log_dir)
    if not os.path.exists(checkpoint_dir):
        os.mkdir(checkpoint_dir)


def network(use_pretrained=True):
    model = tf.keras.Sequential()
    model.add(kl.InputLayer(input_shape=(224, 224, 3)))
    if use_pretrained:
        if pretrained_name == 'vgg':
            vgg = VGG16(weights='imagenet', input_shape=(224, 224, 3), include_top=False)
            vgg.trainable = False
            model.add(vgg)
        if pretrained_name == 'mobilenet':
            mobnet = MobileNetV2(weights='imagenet', input_shape=(224, 224, 3), include_top=False)
            mobnet.trainable = False
            model.add(mobnet)
    else:
        # First conv block
        model.add(kl.Conv2D(filters = 96, kernel_size=7, padding='same', strides=2))
        model.add(tf.keras.layers.ReLU())
        model.add(kl.MaxPooling2D(pool_size=(3, 3)))
        # Second conv block
        model.add(kl.Conv2D(filters = 256, kernel_size=5, padding='same', strides=1))
        model.add(tf.keras.layers.ReLU())
        model.add(kl.MaxPooling2D(pool_size=(2, 2)))
        # Third-Fourth-Fifth conv block
        for i in range(3):
            model.add(kl.Conv2D(filters = 512, kernel_size=3, padding='same', strides=1))
            model.add(tf.keras.layers.ReLU())
        model.add(kl.MaxPooling2D(pool_size=(3, 3)))
    # Flatten
    model.add(kl.Flatten())
    # First FC
    model.add(kl.Dense(1024))
    # Second Fc
    model.add(kl.Dense(256))
    # Output FC with sigmoid at the end
    model.add(kl.Dense(4, activation='sigmoid', name='prediction'))
    return model
'''
https://keras.io/guides/writing_a_training_loop_from_scratch/
Compile into a static graph any function that take tensors as input to apply global performance optimizations.
'''

@tf.function
def macro_f1(y, y_hat, thresh=0.5):
    """Compute the macro F1-score on a batch of observations (average F1 across labels)

    Args:
        y (int32 Tensor): labels array of shape (BATCH_SIZE, N_LABELS)
        y_hat (float32 Tensor): probability matrix from forward propagation of shape (BATCH_SIZE, N_LABELS)
        thresh: probability value above which we predict positive

    Returns:
        macro_f1 (scalar Tensor): value of macro F1 for the batch
    """
    y_pred = tf.cast(tf.greater(y_hat, thresh), tf.float32)
    tp = tf.cast(tf.math.count_nonzero(y_pred * y, axis=0), tf.float32)
    fp = tf.cast(tf.math.count_nonzero(y_pred * (1 - y), axis=0), tf.float32)
    fn = tf.cast(tf.math.count_nonzero((1 - y_pred) * y, axis=0), tf.float32)
    f1 = 2 * tp / (2 * tp + fn + fp + 1e-16)
    macro_f1 = tf.reduce_mean(f1)
    return macro_f1

@tf.function
def loss_calc(y, logits):
    losses = [loss_fn(y[:,0], logits[:,0]),
              loss_fn(y[:,1], logits[:,1]),
              loss_fn(y[:,2], logits[:,2]),
              loss_fn(y[:,3], logits[:,3])
             ]
    loss_bor.update_state(losses[0])
    loss_eng.update_state(losses[1])
    loss_conf.update_state(losses[2])
    loss_frus.update_state(losses[3])
    return sum(losses)


@tf.function
def acc_update(y, logits):
    acc_bor.update_state(y[0], logits[0])
    acc_eng.update_state(y[1], logits[1])
    acc_conf.update_state(y[2], logits[2])
    acc_frus.update_state(y[3], logits[3])


@tf.function
def train_step(x, y):
    with tf.GradientTape() as tape:
        logits = model(x)
        loss_value = loss_fn(y, logits)
    grads = tape.gradient(loss_value, model.trainable_weights)
    optimizer.apply_gradients(zip(grads, model.trainable_weights))
    # Track progress
    train_loss_avg.update_state(loss_value)
    train_accuracy.update_state(macro_f1(y, logits))
    #acc_update(y, logits)
    return loss_value

@tf.function
def test_step(model, x, y, set_name):
    logits = model(x)
    if set_name == 'val':
        val_accuracy.update_state(y, logits)
    else:
        test_accuracy.update_state(y, logits)


if __name__ == '__main__':
    preprocessing_class = DataPreprocessing()

    # Open train set
    tfrecord_path = 'tfrecords/train.tfrecords'
    train_set = tf.data.TFRecordDataset(tfrecord_path)
    # Parse the record into tensors with map.
    train_set = train_set.map(preprocessing_class.decode)
    train_set = train_set.shuffle(1)
    train_set = train_set.batch(BATCH_SIZE)

    # Open test set
    tfrecord_path = 'tfrecords/test.tfrecords'
    test_set = tf.data.TFRecordDataset(tfrecord_path)
    # Parse the record into tensors with map.
    test_set = test_set.map(preprocessing_class.decode)
    test_set = test_set.shuffle(1)
    test_set = test_set.batch(BATCH_SIZE)

    # Open val set
    tfrecord_path = 'tfrecords/val.tfrecords'
    val_set = tf.data.TFRecordDataset(tfrecord_path)
    # Parse the record into tensors with map.
    val_set = val_set.map(preprocessing_class.decode)
    val_set = val_set.shuffle(1)
    val_set = val_set.batch(BATCH_SIZE)

    # Create the model
    model = network()

    # Optimizers and metrics
    loss_fn = tf.keras.losses.BinaryCrossentropy()
    optimizer = tf.keras.optimizers.Adam(learning_rate=LR)

    train_loss_avg = tf.keras.metrics.Mean()
    train_accuracy = tf.keras.metrics.CategoricalAccuracy()
    val_accuracy = tf.keras.metrics.CategoricalAccuracy()
    test_accuracy = tf.keras.metrics.CategoricalAccuracy()
    # Specific metric
    '''
    acc_eng = tf.keras.metrics.CategoricalAccuracy()
    acc_bor = tf.keras.metrics.CategoricalAccuracy()
    acc_conf = tf.keras.metrics.CategoricalAccuracy()
    acc_frus = tf.keras.metrics.CategoricalAccuracy()
    loss_eng = tf.keras.metrics.Mean()
    loss_bor = tf.keras.metrics.Mean()
    loss_conf = tf.keras.metrics.Mean()
    loss_frus = tf.keras.metrics.Mean()
    '''

    create_log_dir(log_dir, checkpoint_dir)

    last_models = os.listdir(checkpoint_dir)
    if last_models:
        last_model_path = checkpoint_dir + '/' + last_models[-1]
        first_epoch = int(last_models[-1].split("_")[1]) + 1
        model = tf.keras.models.load_model(last_model_path)
    else:
        first_epoch = 0
        model = network()

    # Train
    for epoch in range(first_epoch, EPOCHS):
        try:
            # Training loop
            for x_batch_train, y_batch_train in tqdm(train_set, total=256):
                # Do step
                loss_value = train_step(x_batch_train, y_batch_train)

            # Test on validation set
            for x_batch_val, y_batch_val in val_set:
                test_step(x_batch_val, y_batch_val, 'val')

            # Write in the summary
            with train_summary_writer.as_default():
                tf.summary.scalar('Train Loss', train_loss_avg.result(), step=epoch)
                tf.summary.scalar('Train F1 Score', train_accuracy.result(), step=epoch)
                tf.summary.scalar('Val F1 Score', val_accuracy.result(), step=epoch)
                # Specific feature metric
                '''
                # - Loss
                tf.summary.scalar('Bored Loss', loss_bor.result(), step=epoch)
                tf.summary.scalar('Engaged Loss', loss_eng.result(), step=epoch)
                tf.summary.scalar('Confused Loss', loss_conf.result(), step=epoch)
                tf.summary.scalar('Frustrated Loss', loss_frus.result(), step=epoch)
                # - Acc
                tf.summary.scalar('Bored Precision', acc_bor.result(), step=epoch)
                tf.summary.scalar('Engaged Precision', acc_eng.result(), step=epoch)
                tf.summary.scalar('Confused Precision', acc_conf.result(), step=epoch)
                tf.summary.scalar('Frustrated Precision', acc_frus.result(), step=epoch)
                '''

            # Reset training metrics at the end of each epoch
            train_accuracy.reset_states()
            val_accuracy.reset_states()
            '''
            loss_bor.reset_states()
            loss_eng.reset_states()
            loss_conf.reset_states()
            loss_frus.reset_states()
            acc_bor.reset_states()
            acc_eng.reset_states()
            acc_conf.reset_states()
            acc_frus.reset_states()
            '''

            if epoch % 25 == 0:
                tf.keras.models.save_model(model, '{}/Epoch_{}_model.hp5'.format(checkpoint_dir, str(epoch)),
                                           save_format="h5")

        except KeyboardInterrupt:
            print("Keyboard Interruption...")
            # Save model
            tf.keras.models.save_model(model, '{}/Epoch_{}_model.hp5'.format(checkpoint_dir, str(epoch)),
                                       save_format="h5")
            break

    # Test on validation set
    for x_batch_test, y_batch_test in test_set:
        test_step(model, x_batch_test, y_batch_test, 'test')
    test_set_acc = test_accuracy.result().numpy()
    print("Accuracy on test set is", test_set_acc)
