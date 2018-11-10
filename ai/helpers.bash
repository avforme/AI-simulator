# AIPlanner - Deep Learning Financial Planner
# Copyright (C) 2018 Gordon Irlam
#
# All rights reserved. This program may not be used, copied, modified,
# or redistributed without permission.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the
# implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
# PURPOSE.

AIPLANNER_HOME=${AIPLANNER_HOME:-$HOME/aiplanner}
PARALLEL=${PARALLEL:-True}
    # "False": run seeds of a job sequentially rather than in parallel.
    # "True": run seeds of a job in parallel.
    # "Jobs": run seeds and jobs in parallel; need to then wait; train.log is not saved.
SEEDS=${SEEDS:-10}

AI_DIR=$AIPLANNER_HOME/ai
source $AI_DIR/setenv

EXTRA_ARGS=$*
CONFIG_FILE=${CONFIG_FILE:-$AI_DIR/aiplanner-scenario.txt}
TRAIN_FILE=${TRAIN_FILE:-$AI_DIR/aiplanner-scenario-train.txt}
SINGLE_EVAL_FILE=$AI_DIR/aiplanner-scenario-single-eval.txt
COUPLE_EVAL_FILE=$AI_DIR/aiplanner-scenario-couple-eval.txt

train () {

    local MODEL_NAME=$1
    local ARGS=$2

    if [ $PARALLEL = True -o $PARALLEL = Jobs ]; then

        local SEED=0
        while [ $SEED -lt $SEEDS ]; do
            local MODEL_DIR=aiplanner.$MODEL_NAME-seed_$SEED.tf
            # Output directory must not exist when tensorflow save() is called to save the model hence we can't write the log within it; instead log to a tempfile.
            local TEMPFILE=`tempfile -p train`
            local TEMPFILES[$SEED]=$TEMPFILE
            $AI_DIR/train_ppo1.py -c $CONFIG_FILE -c $TRAIN_FILE --model-dir=$MODEL_DIR $ARGS --train-seed=$SEED $EXTRA_ARGS > $TEMPFILE 2>&1 &
            SEED=`expr $SEED + 1`
        done

        if [ $PARALLEL = True ]; then
            wait
            local SEED=0
            while [ $SEED -lt $SEEDS ]; do
                local MODEL_DIR=aiplanner.$MODEL_NAME-seed_$SEED.tf
                mv ${TEMPFILES[$SEED]} $MODEL_DIR/train.log
                SEED=`expr $SEED + 1`
            done
        fi

    else

        local SEED=0
        set -o pipefail
        while [ $SEED -lt $SEEDS ]; do
            local MODEL_DIR=aiplanner.$MODEL_NAME-seed_$SEED.tf
            local TEMPFILE=`tempfile -p train`
            $AI_DIR/train_ppo1.py -c $CONFIG_FILE -c $TRAIN_FILE --model-dir=$MODEL_DIR $ARGS --train-seed=$SEED $EXTRA_ARGS 2>&1 | tee -a $TEMPFILE || exit 1
            mv $TEMPFILE $MODEL_DIR/train.log
            SEED=`expr $SEED + 1`
        done

    fi
}

evaluate () {

    local MODEL_NAME=$1
    local EVAL_NAME=$2
    local ARGS=$3

    if [ $PARALLEL = True -o $PARALLEL = Jobs ]; then

        local SEED=0
        while [ $SEED -lt $SEEDS ]; do
            local MODEL_DIR=aiplanner.$MODEL_NAME-seed_$SEED.tf
            local RESULT_DIR=$MODEL_DIR/$EVAL_NAME
            mkdir $RESULT_DIR 2> /dev/null
            $AI_DIR/eval_model.py -c $CONFIG_FILE --model-dir=$MODEL_DIR --result-dir=$RESULT_DIR $ARGS $EXTRA_ARGS > $RESULT_DIR/eval.log 2>&1 &
            SEED=`expr $SEED + 1`
        done

        if [ $PARALLEL = True ]; then
            wait
        fi

    else
    
        local SEED=0
        set -o pipefail
        while [ $SEED -lt $SEEDS ]; do
            local MODEL_DIR=aiplanner.$MODEL_NAME-seed_$SEED.tf
            local RESULT_DIR=$MODEL_DIR/$EVAL_NAME
            mkdir $RESULT_DIR 2> /dev/null
            $AI_DIR/eval_model.py -c $CONFIG_FILE --model-dir=$MODEL_DIR --result-dir=$RESULT_DIR $ARGS $EXTRA_ARGS 2>&1 | tee $RESULT_DIR/eval.log || exit 1
            SEED=`expr $SEED + 1`
        done

    fi
}
