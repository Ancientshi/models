import os
import time
import numpy as np
from sklearn.metrics import roc_auc_score

import oneflow as flow

from config import get_args
from dataloader_utils import OFRecordDataLoader
from wide_and_deep_module import WideAndDeep
from util import dump_to_npy, save_param_npy


if __name__ == "__main__":
    args = get_args()

    train_dataloader = OFRecordDataLoader(args, data_root=args.data_dir)
    val_dataloader = OFRecordDataLoader(args, data_root=args.data_dir, mode="val")
    wdl_module = WideAndDeep(args)
    if args.model_load_dir != "":
        print("load checkpointed model from ", args.model_load_dir)
        wdl_module.load_state_dict(flow.load(args.model_load_dir))

    if args.save_initial_model and args.model_save_dir != "":
        path = os.path.join(args.model_save_dir, "initial_checkpoint")
        if not os.path.isdir(path):
            flow.save(wdl_module.state_dict(), path)
    # save_param_npy(wdl_module)

    bce_loss = flow.nn.BCELoss(reduction="none")

    wdl_module.to("cuda")
    bce_loss.to("cuda")

    of_sgd = flow.optim.SGD(wdl_module.parameters(), lr=args.learning_rate)

    class WideAndDeepGraph(flow.nn.Graph):
        def __init__(self):
            super(WideAndDeepGraph, self).__init__()
            self.module = wdl_module
            self.bce_loss = bce_loss

        def build(self, labels, dense_fields, wide_sparse_fields, deep_sparse_fields):
            with flow.no_grad():
                return self.graph(
                    labels, dense_fields, wide_sparse_fields, deep_sparse_fields
                )

        def graph(self, labels, dense_fields, wide_sparse_fields, deep_sparse_fields):
            labels = labels.to("cuda").to(dtype=flow.float32)
            dense_fields = dense_fields.to("cuda")
            wide_sparse_fields = wide_sparse_fields.to("cuda")
            deep_sparse_fields = deep_sparse_fields.to("cuda")

            predicts = self.module(dense_fields, wide_sparse_fields, deep_sparse_fields)
            loss = self.bce_loss(predicts, labels)
            return predicts, labels, loss

    class WideAndDeepTrainGraph(WideAndDeepGraph):
        def __init__(self):
            super(WideAndDeepTrainGraph, self).__init__()
            self.add_optimizer("sgd", of_sgd)

        def build(self, labels, dense_fields, wide_sparse_fields, deep_sparse_fields):
            predicts, labels, loss = self.graph(
                labels, dense_fields, wide_sparse_fields, deep_sparse_fields
            )
            loss.backward()
            return predicts, labels, loss

    eval_graph = WideAndDeepGraph()
    train_graph = WideAndDeepTrainGraph()

    losses = []
    wdl_module.train()

    for i in range(args.max_iter):
        (
            labels,
            dense_fields,
            wide_sparse_fields,
            deep_sparse_fields,
        ) = train_dataloader()
        predicts, labels, loss = train_graph(
            labels, dense_fields, wide_sparse_fields, deep_sparse_fields
        )
        losses.append(loss.numpy().mean())

        if (i + 1) % args.print_interval == 0:
            l = sum(losses) / len(losses)
            print(f"iter {i} train_loss {l} time {time.time()}")
            losses = []

            if args.eval_batchs <= 0:
                continue

            eval_loss = 0.0
            lables_list = []
            predicts_list = []
            wdl_module.eval()
            for j in range(args.eval_batchs):
                (
                    labels,
                    dense_fields,
                    wide_sparse_fields,
                    deep_sparse_fields,
                ) = val_dataloader()
                predicts, labels, loss = eval_graph(
                    labels, dense_fields, wide_sparse_fields, deep_sparse_fields
                )

                eval_loss += loss.numpy().mean()
                lables_list.append(labels.numpy())
                predicts_list.append(predicts.numpy())
            all_labels = np.concatenate(lables_list, axis=0)
            all_predicts = np.concatenate(predicts_list, axis=0)
            auc = (
                "NaN"
                if np.isnan(all_predicts).any()
                else roc_auc_score(all_labels, all_predicts)
            )
            print(f"iter {i} eval_loss {eval_loss/args.eval_batchs} auc {auc}")

            wdl_module.train()
