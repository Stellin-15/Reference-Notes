# ============================================================
# L07: TensorFlow and Keras — Production-Grade Training
# ============================================================
# WHAT: TensorFlow 2.x with Keras APIs: model building
#       (Sequential / Functional / Subclassing), tf.data
#       pipelines, callbacks, mixed precision, TPU training,
#       model export (SavedModel, TFLite), and TF Serving.
# WHY:  TensorFlow owns the production deployment ecosystem:
#       TF Serving (high-throughput REST/gRPC), TFLite (mobile/edge),
#       TF.js (browser), and TPU support (Google Cloud). If your
#       models ship to Google infrastructure, Android, or
#       TF Serving clusters, you need TF, not PyTorch.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    TensorFlow 2.x unified eager execution (like PyTorch) with
    graph execution (@tf.function). The default is eager — code
    runs immediately, Python-style. @tf.function traces your
    Python function once and compiles it to a static TF graph,
    eliminating Python overhead on subsequent calls.

    Keras is TF's high-level API. Three styles:
      Sequential: linear stack of layers (simplest).
      Functional: directed acyclic graph (multiple I/O, skip connections).
      Subclassing: define forward pass in call() (most flexible).

    tf.data is TF's input pipeline system. It handles prefetching,
    parallel preprocessing, caching, and shuffling in a lazy,
    composable pipeline — critical for GPU utilization.

PRODUCTION USE CASE:
    - Large-scale image classification served by TF Serving:
      REST API, dynamic batching, multiple model versions,
      A/B testing between model versions.
    - TFLite model on Android app for on-device inference:
      no network call, no latency, privacy-preserving.
    - TPU training on Google Cloud: same Keras code, 10-100x
      cheaper than A100 for large models (BERT, ResNet-101).

COMMON MISTAKES:
    1. Mixing eager and graph-mode assumptions: Python print()
       inside @tf.function only executes once (during tracing),
       not on every call. Use tf.print() for graph-mode logging.
    2. Not calling .prefetch(AUTOTUNE) on tf.data pipeline —
       GPU sits idle waiting for next batch.
    3. Saving with model.save('model.h5') for complex models
       with custom objects — .h5 doesn't support all TF features.
       Use SavedModel format (model.save('model/')) instead.
    4. Using model.predict() for single samples in a loop —
       it has overhead per call. Batch predictions, or call
       model(input, training=False) directly.
    5. Forgetting to set training=False (or model.eval()) during
       inference — Dropout and BatchNormalization behave
       differently between training and inference modes.
    6. Mixed precision + loss scaling: Keras handles this
       automatically via LossScaleOptimizer when you set the
       global policy. Don't manually scale losses in Keras.
"""

import numpy as np

try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers, callbacks, mixed_precision
    TF_AVAILABLE = True
    print(f"TensorFlow version: {tf.__version__}")
except ImportError:
    TF_AVAILABLE = False
    print("TensorFlow not installed. All code is reference-only.")


# ============================================================
# SECTION 1: THREE KERAS MODEL BUILDING STYLES
# ============================================================

# --- 1A: Sequential API ---
# WHAT: Linear stack of layers. Each layer has one input, one output.
# WHY:  Best for simple architectures. Cannot express skip connections,
#       multiple inputs/outputs, or layer sharing.
# WHEN: Prototypes, simple classifiers, when teaching Keras.

def build_sequential_model(input_dim: int = 784, num_classes: int = 10):
    """MLP for tabular or flattened image data."""
    model = keras.Sequential([
        # Input layer: specifies shape so Keras can build the graph.
        # Without it, the model is built lazily on first call.
        layers.Input(shape=(input_dim,)),
        layers.Dense(512, activation='relu'),
        layers.BatchNormalization(),    # normalize activations
        layers.Dropout(0.3),           # regularization
        layers.Dense(256, activation='relu'),
        layers.Dropout(0.3),
        layers.Dense(num_classes, activation='softmax'),  # output probabilities
    ], name='sequential_mlp')
    return model


# --- 1B: Functional API ---
# WHAT: Define computation graph explicitly — inputs and outputs are
#       symbolic tensors. Each layer call returns a symbolic tensor.
# WHY:  Enables: skip connections (ResNet), multiple inputs (multimodal),
#       multiple outputs (multi-task), shared layers.
# WHEN: ResNet-style skip connections, siamese networks, multi-task.

def build_functional_model(input_dim: int = 784, num_classes: int = 10):
    """MLP with a residual (skip) connection using Functional API."""
    inputs = keras.Input(shape=(input_dim,))

    x = layers.Dense(512, activation='relu')(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.3)(x)

    # Shortcut / skip connection: allows gradient to flow directly
    # from input to later layer, bypassing potentially stuck layers.
    # Project input to match hidden dim if shapes differ.
    shortcut = layers.Dense(256)(inputs)   # match the dimension of x_out
    x = layers.Dense(256)(x)
    x = layers.Add()([x, shortcut])       # element-wise sum — the residual
    x = layers.Activation('relu')(x)
    x = layers.Dropout(0.3)(x)

    outputs = layers.Dense(num_classes, activation='softmax')(x)

    return keras.Model(inputs=inputs, outputs=outputs, name='functional_resmlp')


# --- 1C: Model Subclassing ---
# WHAT: Define layers in __init__, forward pass in call().
#       Equivalent to PyTorch nn.Module.
# WHY:  Maximum flexibility — dynamic computation graphs, custom
#       training logic, non-standard architectures.
# WHEN: GANs (discriminator/generator interleaved), meta-learning,
#       models with conditional execution (e.g., mixture-of-experts).

class SubclassedCNN(keras.Model):
    """
    CNN for image classification using Model subclassing.
    Flexible call() allows dynamic architectures if needed.
    """
    def __init__(self, num_classes: int = 10, name: str = 'cnn'):
        super().__init__(name=name)
        # Build layers in __init__.
        # These are tracked as model weights automatically.
        self.conv1 = layers.Conv2D(32, 3, padding='same', activation='relu')
        self.bn1 = layers.BatchNormalization()
        self.pool1 = layers.MaxPooling2D(2)

        self.conv2 = layers.Conv2D(64, 3, padding='same', activation='relu')
        self.bn2 = layers.BatchNormalization()
        self.pool2 = layers.MaxPooling2D(2)

        # GlobalAveragePooling2D: (batch, H, W, C) → (batch, C).
        # More robust to spatial shifts than GlobalMaxPooling2D.
        self.gap = layers.GlobalAveragePooling2D()

        self.dropout = layers.Dropout(0.5)
        self.dense1 = layers.Dense(128, activation='relu')
        self.outputs_layer = layers.Dense(num_classes, activation='softmax')

    def call(self, inputs, training: bool = False):
        """
        Forward pass. training=True: dropout and BN use training behavior.
        training=False: dropout off, BN uses running statistics.
        Keras passes training=True automatically during model.fit().
        """
        x = self.conv1(inputs)
        x = self.bn1(x, training=training)   # pass training to BN!
        x = self.pool1(x)

        x = self.conv2(x)
        x = self.bn2(x, training=training)
        x = self.pool2(x)

        x = self.gap(x)
        x = self.dropout(x, training=training)  # pass training to Dropout!
        x = self.dense1(x)
        return self.outputs_layer(x)


# ============================================================
# SECTION 2: MODEL COMPILATION AND TRAINING
# ============================================================
# WHAT: model.compile() sets loss, optimizer, and metrics.
#       model.fit() runs the training loop.
# WHY:  Keras's training engine handles gradient tape, gradient
#       accumulation, device placement, mixed precision loss
#       scaling, and metric aggregation automatically.
#       You get production-grade training with minimal code.

if TF_AVAILABLE:

    def compile_and_train_example():
        """Demonstrates compile + fit with key options."""
        model = build_functional_model(input_dim=784, num_classes=10)

        # Optimizer options:
        #   Adam: adaptive LR per parameter, good default.
        #   AdamW: Adam + weight decay (better regularization, esp. for transformers).
        #   SGD + momentum: slower but sometimes better final accuracy.
        #   RMSprop: good for RNNs (historically).
        optimizer = keras.optimizers.AdamW(
            learning_rate=1e-3,
            weight_decay=1e-4   # L2 regularization on weights (not biases)
        )

        # Loss functions:
        #   sparse_categorical_crossentropy: integer labels (0, 1, 2, ...)
        #   categorical_crossentropy: one-hot labels
        #   binary_crossentropy: binary (0 or 1) labels
        #   from_logits=True: pass raw logits, not softmax output.
        #     More numerically stable — skip the final softmax in the model.
        model.compile(
            optimizer=optimizer,
            loss=keras.losses.SparseCategoricalCrossentropy(from_logits=False),
            metrics=[
                keras.metrics.SparseCategoricalAccuracy(name='accuracy'),
                keras.metrics.SparseTopKCategoricalAccuracy(k=5, name='top5_accuracy'),
            ]
        )

        # model.summary() prints layer-by-layer parameter counts.
        model.summary()
        return model


# ============================================================
# SECTION 3: tf.data INPUT PIPELINE
# ============================================================
# WHAT: tf.data builds lazy, composable input pipelines.
#       Data flows through a chain of transformations, executed
#       just-in-time as the model requests batches.
# WHY:  GPU utilization dies when data loading is the bottleneck.
#       tf.data solves this:
#       - .map(fn, num_parallel_calls=AUTOTUNE): parallel preprocessing.
#       - .prefetch(AUTOTUNE): prepare next batch while model trains on current.
#       - .cache(): load from disk once, keep in memory for subsequent epochs.
#       - .shuffle(buffer_size): randomize order (set buffer_size ≥ dataset size
#         for true shuffling, or as large as memory allows).

if TF_AVAILABLE:
    AUTOTUNE = tf.data.AUTOTUNE  # let TF decide optimal parallelism

    def build_tf_data_pipeline(x_data: np.ndarray, y_data: np.ndarray,
                                batch_size: int = 32,
                                is_training: bool = True):
        """
        Production tf.data pipeline for image/tabular data.
        Order of operations matters for efficiency:
          1. from_tensor_slices (or from files)
          2. shuffle (before cache for true randomization)
          3. map (preprocessing)
          4. cache (after map if preprocessing is deterministic)
          5. batch
          6. prefetch (always last)
        """
        dataset = tf.data.Dataset.from_tensor_slices((x_data, y_data))

        if is_training:
            # Shuffle with a large buffer for good randomization.
            # Smaller buffer = faster startup but less shuffled.
            dataset = dataset.shuffle(
                buffer_size=min(len(x_data), 10000),
                reshuffle_each_iteration=True  # re-shuffle every epoch
            )

        def preprocess(x, y):
            """Preprocessing applied to each sample in parallel."""
            # Example: normalize images to [0, 1].
            x = tf.cast(x, tf.float32) / 255.0
            # Data augmentation (training only):
            if is_training:
                x = tf.image.random_flip_left_right(
                    tf.reshape(x, [28, 28, 1])
                )
                x = tf.reshape(x, [-1])
            return x, y

        # map with num_parallel_calls=AUTOTUNE: TF runs preprocess
        # in multiple threads to saturate CPU while GPU trains.
        dataset = dataset.map(preprocess, num_parallel_calls=AUTOTUNE)

        # cache(): stores preprocessed samples in memory after first epoch.
        # Huge speedup for datasets that fit in RAM.
        # For large datasets: cache to disk: .cache('/path/to/cache')
        dataset = dataset.cache()

        dataset = dataset.batch(
            batch_size,
            drop_remainder=is_training  # drop last incomplete batch during training
        )

        # prefetch(): while model trains on batch N, pipeline prepares batch N+1.
        # AUTOTUNE dynamically adjusts the prefetch buffer size.
        # This is the single highest-impact optimization in tf.data.
        dataset = dataset.prefetch(AUTOTUNE)

        return dataset

    def build_image_pipeline_from_files(file_pattern: str,
                                         batch_size: int = 32,
                                         image_size: tuple = (224, 224)):
        """
        Pipeline that reads images from disk — the production pattern
        when your dataset doesn't fit in RAM.
        """
        # list_files: matches glob pattern, returns dataset of file paths.
        file_ds = tf.data.Dataset.list_files(file_pattern, shuffle=True)

        def load_and_preprocess(path):
            """Read → decode → resize → normalize per file."""
            raw = tf.io.read_file(path)
            image = tf.image.decode_jpeg(raw, channels=3)
            image = tf.image.resize(image, image_size)
            image = tf.cast(image, tf.float32) / 255.0
            # Normalize with ImageNet stats (for pretrained models).
            mean = tf.constant([0.485, 0.456, 0.406])
            std = tf.constant([0.229, 0.224, 0.225])
            image = (image - mean) / std
            return image

        return (file_ds
                .map(load_and_preprocess, num_parallel_calls=AUTOTUNE)
                .batch(batch_size)
                .prefetch(AUTOTUNE))


# ============================================================
# SECTION 4: CALLBACKS
# ============================================================
# WHAT: Callbacks are hooks that execute at specific training events
#       (epoch start/end, batch start/end, training end).
# WHY:  They keep training code clean while adding essential features:
#       saving best model, stopping early, reducing LR on plateau,
#       logging to TensorBoard. All production training uses callbacks.

if TF_AVAILABLE:

    def build_production_callbacks(checkpoint_path: str = './best_model/',
                                    log_dir: str = './logs/'):
        """
        Standard callback set for production training.
        """
        return [
            # Save the best model by validation loss.
            # save_best_only=True: only overwrites when val_loss improves.
            # save_weights_only=False: saves full SavedModel (architecture + weights).
            callbacks.ModelCheckpoint(
                filepath=checkpoint_path,
                monitor='val_loss',
                save_best_only=True,
                save_weights_only=False,
                verbose=1
            ),

            # Stop training early if val_loss stops improving.
            # patience=10: tolerate 10 epochs of no improvement before stopping.
            # restore_best_weights=True: revert to the best epoch's weights.
            # min_delta=1e-4: improvement must be at least this large.
            callbacks.EarlyStopping(
                monitor='val_loss',
                patience=10,
                restore_best_weights=True,
                min_delta=1e-4,
                verbose=1
            ),

            # Reduce LR when training plateaus.
            # factor=0.5: multiply LR by 0.5 (halve it).
            # patience=5: wait 5 epochs before reducing.
            # min_lr=1e-7: never go below this LR.
            # Useful when: you want automatic LR decay without hand-tuning.
            callbacks.ReduceLROnPlateau(
                monitor='val_loss',
                factor=0.5,
                patience=5,
                min_lr=1e-7,
                verbose=1
            ),

            # TensorBoard: visualize loss curves, gradients, weight histograms.
            # Launch: tensorboard --logdir ./logs/
            callbacks.TensorBoard(
                log_dir=log_dir,
                histogram_freq=1,      # log weight histograms every epoch
                write_graph=True,      # visualize computation graph
                update_freq='epoch',   # or 'batch' for per-step logging
            ),

            # LambdaCallback: quick custom logic without subclassing.
            callbacks.LambdaCallback(
                on_epoch_end=lambda epoch, logs: print(
                    f"Custom callback: epoch {epoch+1}, "
                    f"val_acc={logs.get('val_accuracy', 0):.4f}"
                )
            ),
        ]


# ============================================================
# SECTION 5: CUSTOM TRAINING LOOP WITH tf.GradientTape
# ============================================================
# WHAT: Manually record forward pass and compute gradients.
#       Replaces model.fit() for non-standard training.
# WHY:  model.fit() handles 95% of cases. Use GradientTape when:
#       - GAN training (discriminator and generator updates in
#         specific order, possibly multiple updates per batch).
#       - Meta-learning (MAML — gradient of gradient).
#       - Custom gradient clipping, gradient penalties (WGAN-GP).
#       - Interleaved multi-task update schedules.

if TF_AVAILABLE:

    @tf.function  # compile to TF graph for speed
    def train_step(model, optimizer, loss_fn, x_batch, y_batch):
        """
        Single training step using GradientTape.
        @tf.function: traces once, runs as optimized graph.
        Important: no Python side effects inside @tf.function.
        """
        # GradientTape records all operations on watched tensors
        # (model.trainable_variables are watched by default).
        with tf.GradientTape() as tape:
            # training=True: enables Dropout, uses batch stats for BN.
            predictions = model(x_batch, training=True)
            loss = loss_fn(y_batch, predictions)

            # If using mixed precision, the optimizer may scale the loss
            # internally. Keras handles this transparently.

        # Compute gradients of loss w.r.t. all trainable variables.
        gradients = tape.gradient(loss, model.trainable_variables)

        # Gradient clipping: clip by global norm.
        gradients, global_norm = tf.clip_by_global_norm(gradients, clip_norm=1.0)

        # Apply gradients — the optimizer step.
        optimizer.apply_gradients(zip(gradients, model.trainable_variables))

        return loss, global_norm

    @tf.function
    def val_step(model, loss_fn, x_batch, y_batch):
        """Validation step — no gradient recording, training=False."""
        predictions = model(x_batch, training=False)
        loss = loss_fn(y_batch, predictions)
        return loss, predictions

    def custom_training_loop(model, train_ds, val_ds, epochs: int = 10):
        """Full custom training loop with GradientTape."""
        optimizer = keras.optimizers.AdamW(learning_rate=1e-3)
        loss_fn = keras.losses.SparseCategoricalCrossentropy()

        train_loss_metric = keras.metrics.Mean(name='train_loss')
        val_loss_metric = keras.metrics.Mean(name='val_loss')
        val_accuracy_metric = keras.metrics.SparseCategoricalAccuracy(name='val_acc')

        best_val_loss = float('inf')

        for epoch in range(epochs):
            train_loss_metric.reset_states()
            val_loss_metric.reset_states()
            val_accuracy_metric.reset_states()

            # Training
            for x_batch, y_batch in train_ds:
                loss, _ = train_step(model, optimizer, loss_fn, x_batch, y_batch)
                train_loss_metric.update_state(loss)

            # Validation
            for x_batch, y_batch in val_ds:
                val_loss, preds = val_step(model, loss_fn, x_batch, y_batch)
                val_loss_metric.update_state(val_loss)
                val_accuracy_metric.update_state(y_batch, preds)

            print(
                f"Epoch {epoch+1}/{epochs} — "
                f"train_loss={train_loss_metric.result():.4f} "
                f"val_loss={val_loss_metric.result():.4f} "
                f"val_acc={val_accuracy_metric.result():.4f}"
            )

            # Manual checkpoint saving
            current_val_loss = val_loss_metric.result().numpy()
            if current_val_loss < best_val_loss:
                best_val_loss = current_val_loss
                model.save('./best_model_custom/')
                print(f"  Saved best model (val_loss={best_val_loss:.4f})")


# ============================================================
# SECTION 6: MIXED PRECISION TRAINING
# ============================================================
# WHAT: Compute in float16, store weights in float32.
#       Keras handles loss scaling automatically.
# WHY:  2x faster training on V100/A100 (Tensor Cores).
#       2x less GPU memory for activations.
#       Keras's LossScaleOptimizer wraps your optimizer and
#       scales losses automatically — no manual GradScaler needed.
# NOTE: bfloat16 is preferred on TPUs and A100 (wider exponent
#       range than float16, no loss scaling needed).

if TF_AVAILABLE:

    def setup_mixed_precision(use_gpu: bool = True):
        """Enable global mixed precision policy."""
        policy_name = 'mixed_float16' if use_gpu else 'mixed_bfloat16'
        # set_global_policy: ALL subsequent layers use this dtype policy.
        # Compute dtype: float16 (forward/backward pass).
        # Variable dtype: float32 (weight storage — prevents underflow).
        mixed_precision.set_global_policy(policy_name)
        print(f"Mixed precision policy: {policy_name}")

    def build_mixed_precision_model(num_classes: int = 10):
        """Build model after setting global mixed precision policy."""
        # After set_global_policy, layers automatically use float16 for
        # compute and float32 for variables. No code changes needed.
        model = build_sequential_model(num_classes=num_classes)

        # When compiling with mixed_float16, Keras wraps the optimizer in
        # LossScaleOptimizer automatically, which handles loss scaling.
        model.compile(
            optimizer=keras.optimizers.Adam(1e-3),
            loss='sparse_categorical_crossentropy',
            metrics=['accuracy']
        )
        return model


# ============================================================
# SECTION 7: TPU TRAINING
# ============================================================
# WHAT: TPUStrategy distributes training across TPU cores.
#       Same Keras code works on CPU/GPU/TPU with different strategies.
# WHY:  TPUs are Google's custom ML chips. On Google Cloud, TPU v4
#       chips can be 10-50x cheaper per FLOP than A100 GPUs for
#       large-scale training. BERT was originally trained on TPUs.
# NOTE: tf.distribute API:
#       MirroredStrategy: multi-GPU, single machine.
#       MultiWorkerMirroredStrategy: multi-GPU, multi-machine.
#       TPUStrategy: TPU pods.
#       All use the same API — swap strategy, keep the rest.

if TF_AVAILABLE:

    def build_model_on_tpu():
        """
        All model creation and compilation must happen inside strategy.scope().
        The strategy ensures variables are created on the correct devices.
        """
        try:
            # Connect to TPU (Google Colab or GCP).
            resolver = tf.distribute.cluster_resolver.TPUClusterResolver()
            tf.config.experimental_connect_to_cluster(resolver)
            tf.tpu.experimental.initialize_tpu_system(resolver)
            strategy = tf.distribute.TPUStrategy(resolver)
            print(f"TPU: {strategy.num_replicas_in_sync} cores")
        except Exception:
            # Fall back to GPU/CPU MirroredStrategy if no TPU.
            strategy = tf.distribute.MirroredStrategy()
            print(f"MirroredStrategy: {strategy.num_replicas_in_sync} replicas")

        with strategy.scope():
            # Inside scope: variables are created on each replica.
            model = build_functional_model(input_dim=784, num_classes=10)
            model.compile(
                optimizer=keras.optimizers.Adam(1e-3),
                loss='sparse_categorical_crossentropy',
                metrics=['accuracy']
            )
        return model, strategy


# ============================================================
# SECTION 8: MODEL SERIALIZATION AND DEPLOYMENT
# ============================================================

if TF_AVAILABLE:

    def save_and_load_model_demo(model, save_dir: str = './saved_model/'):
        """
        SavedModel format (recommended for production):
          - Saves computation graph + weights + serving signatures.
          - Can be loaded in Python, C++, Java, Go.
          - Used by TF Serving, TF Lite converter, TF.js converter.
          - Supports custom objects without extra configuration.
        H5 format (legacy):
          - Simpler single file (.h5 / .keras).
          - Doesn't support all TF features (e.g., custom training steps).
          - Use for simple Keras models only.
        """
        # Preferred: SavedModel format.
        model.save(save_dir)
        print(f"Model saved to {save_dir} (SavedModel format)")

        # Load for inference.
        loaded_model = tf.saved_model.load(save_dir)
        # Or: keras.models.load_model(save_dir) — keeps Keras API.

        # H5 format — simpler but less portable.
        # model.save('model.h5')  # or 'model.keras' (newer extension)

    def convert_to_tflite(model, output_path: str = 'model.tflite',
                           quantize: bool = True):
        """
        TFLite Conversion: optimize for mobile/edge deployment.
        Steps: SavedModel → TFLite Converter → .tflite file → device.

        INT8 Post-Training Quantization:
          - Quantizes weights and activations from FP32 to INT8.
          - 4x model size reduction.
          - 2-4x faster inference on ARM/edge hardware.
          - Accuracy loss: typically <1% for classification.
          - Requires a 'representative dataset' for calibration
            (determines quantization ranges).
        """
        converter = tf.lite.TFLiteConverter.from_keras_model(model)

        if quantize:
            # INT8 post-training quantization.
            converter.optimizations = [tf.lite.Optimize.DEFAULT]

            # Representative dataset: 100-500 samples from validation set.
            # Used to calibrate activation quantization ranges.
            def representative_data_gen():
                for _ in range(100):
                    # Yield a single batch — shape must match model input.
                    yield [np.random.randn(1, 784).astype(np.float32)]

            converter.representative_dataset = representative_data_gen
            # Force INT8 output — full integer quantization.
            converter.target_spec.supported_ops = [
                tf.lite.OpsSet.TFLITE_BUILTINS_INT8
            ]
            converter.inference_input_type = tf.int8
            converter.inference_output_type = tf.int8

        tflite_model = converter.convert()
        with open(output_path, 'wb') as f:
            f.write(tflite_model)
        print(f"TFLite model saved to {output_path} "
              f"({len(tflite_model) / 1024:.1f} KB)")


# ============================================================
# SECTION 9: @tf.function — GRAPH COMPILATION
# ============================================================
# WHAT: Decorator that traces the Python function once and
#       converts it to a TF computation graph.
# WHY:  Python function calls are slow (~1μs overhead each).
#       A transformer forward pass has thousands of ops.
#       @tf.function eliminates Python overhead: 2-5x speedup
#       for typical training steps.
# LIMITATIONS:
#       - Python side effects (print, list.append) only run during tracing.
#       - Control flow (if/for on tensors) must use tf.cond/tf.while_loop.
#       - Retraces when input shapes change — use input_signature to fix.

if TF_AVAILABLE:

    @tf.function(
        # input_signature: lock the function to this input spec.
        # Prevents retracing for different batch sizes/dtypes.
        # Remove if you need dynamic shapes.
        # input_signature=[
        #     tf.TensorSpec(shape=[None, 784], dtype=tf.float32),
        #     tf.TensorSpec(shape=[None], dtype=tf.int32),
        # ]
    )
    def fast_inference(model, x):
        """
        @tf.function inference. Called thousands of times per second
        in a serving scenario — the graph optimization matters.
        """
        return model(x, training=False)  # training=False: no dropout, use BN running stats

    def tf_function_tracing_demo():
        """Illustrate the tracing behavior of @tf.function."""
        @tf.function
        def add(a, b):
            # This print only fires during tracing (first call per input signature).
            print("Tracing! (Python side effect)")
            # tf.print fires on every execution (graph node).
            tf.print("Executing! a =", a, "b =", b)
            return a + b

        add(tf.constant(1), tf.constant(2))   # traces + executes
        add(tf.constant(3), tf.constant(4))   # only executes (same signature)
        add(tf.constant(1.0), tf.constant(2.0))  # retraces (float != int)


# ============================================================
# SECTION 10: TF SERVING (REFERENCE — SHELL COMMANDS)
# ============================================================
# WHAT: TensorFlow Serving is a production ML serving system.
#       Loads SavedModels, exposes REST and gRPC endpoints,
#       handles request batching, model versioning, A/B tests.
# WHY:  Built for production: handles concurrent requests,
#       batches inputs for throughput, hot-swaps model versions
#       without downtime, exports Prometheus metrics.
#
# SETUP (Docker — the recommended deployment method):
#   docker pull tensorflow/serving
#   docker run -p 8501:8501 \
#     -v /path/to/models:/models/my_model \
#     -e MODEL_NAME=my_model \
#     tensorflow/serving
#
# REST prediction request:
#   POST http://localhost:8501/v1/models/my_model:predict
#   Body: {"instances": [[1.0, 2.0, ..., 784th_value]]}
#
# gRPC is faster for production — use tensorflow-serving-api:
#   from tensorflow_serving.apis import predict_pb2, prediction_service_pb2_grpc
#
# Model versioning:
#   /models/my_model/1/  → version 1 (SavedModel dir)
#   /models/my_model/2/  → version 2
#   TF Serving serves the highest version by default.
#   Configure via model_config_file for A/B routing.
#
# Dynamic batching config (batching_parameters.txt):
#   max_batch_size { value: 128 }
#   batch_timeout_micros { value: 1000 }
#   max_enqueued_batches { value: 100 }
#   num_batch_threads { value: 4 }
#
# This tells Serving to accumulate requests for up to 1ms and
# batch them together for GPU inference — maximizes throughput.


# ============================================================
# SECTION 11: PYTORCH VS TENSORFLOW — WHEN TO USE WHICH
# ============================================================
# PyTorch:
#   + Pythonic, intuitive, easier to debug (eager by default).
#   + Dominant in ML research (most papers ship PyTorch code).
#   + Better for custom architectures and training loops.
#   + Hugging Face ecosystem is PyTorch-first.
#   + torch.compile (2.0) closed the performance gap with TF graphs.
#   - Deployment: TorchServe / ONNX / Triton — more setup vs TF Serving.
#
# TensorFlow:
#   + TF Serving: production-grade, battle-tested at Google scale.
#   + TFLite: best-in-class mobile/edge deployment.
#   + TF.js: run models in the browser.
#   + TPU support: first-class citizen (PyTorch/XLA is improving).
#   + TFX: end-to-end ML production pipelines.
#   - Less flexible for research. @tf.function footguns.
#   - Steeper learning curve for custom training.
#
# RULE OF THUMB (2025):
#   Research / experimentation / NLP → PyTorch.
#   Google Cloud / Android / production serving → TensorFlow.
#   NVIDIA Triton: serves both — increasingly the neutral choice.


# ============================================================
# SECTION 12: COMPLETE EXAMPLE
# ============================================================

if __name__ == '__main__' and TF_AVAILABLE:
    print("=== Building models ===")

    # Sequential
    seq_model = build_sequential_model(input_dim=784, num_classes=10)
    seq_model.compile(optimizer='adam', loss='sparse_categorical_crossentropy',
                      metrics=['accuracy'])

    # Functional
    func_model = build_functional_model(input_dim=784, num_classes=10)
    func_model.compile(optimizer='adam', loss='sparse_categorical_crossentropy',
                       metrics=['accuracy'])

    # Subclassed CNN
    cnn = SubclassedCNN(num_classes=10)

    print("\n=== Building tf.data pipeline ===")
    # Synthetic data — replace with real dataset.
    x_train = np.random.randn(1000, 784).astype(np.float32)
    y_train = np.random.randint(0, 10, 1000).astype(np.int32)
    x_val = np.random.randn(200, 784).astype(np.float32)
    y_val = np.random.randint(0, 10, 200).astype(np.int32)

    train_ds = build_tf_data_pipeline(x_train, y_train, batch_size=32, is_training=True)
    val_ds = build_tf_data_pipeline(x_val, y_val, batch_size=32, is_training=False)

    print("\n=== Training with callbacks ===")
    cb = build_production_callbacks(
        checkpoint_path='./demo_best_model/',
        log_dir='./demo_logs/'
    )

    history = seq_model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=3,           # small for demo
        callbacks=cb,
        verbose=1
    )
    print(f"Training complete. Final val_loss: {history.history['val_loss'][-1]:.4f}")

    print("\n=== Custom training loop demo ===")
    custom_model = build_functional_model(input_dim=784, num_classes=10)
    custom_training_loop(custom_model, train_ds, val_ds, epochs=2)
