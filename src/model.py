from typing import Tuple

import pytorch_lightning as pl
import torch
from torch.optim import SGD, Adam, AdamW
from torch.optim.lr_scheduler import LambdaLR
from torchmetrics.classification.accuracy import Accuracy
from transformers.models.auto.modeling_auto import \
    AutoModelForImageClassification
from transformers.optimization import get_cosine_schedule_with_warmup

model_dict = {
    "b16": "google/vit-base-patch16-224-in21k",
}


class ClassifcationModel(pl.LightningModule):
    def __init__(
        self,
        arch: str = "b16",
        optimizer: str = "sgd",
        lr: float = 3e-2,
        betas: Tuple[float, float] = (0.9, 0.999),
        momentum: float = 0.9,
        weight_decay: float = 0.0,
        scheduler: str = "cosine",
        warmup_steps: int = 0,
        n_classes: int = 10,
        channels_last: bool = False,
    ):
        """Classification Model

        Args:
            arch: Name of ViT architecture (b16)
            optimizer: Name of optimizer (adam | adamw | sgd)
            lr: Learning rate
            betas: Adam betas parameters
            momentum: SGD momentum parameter
            weight_decay: Optimizer weight decay
            scheduler: Name of learning rate scheduler (cosine | none)
            warmup_steps: Number of warmup epochs
            smoothing: Label smoothing alpha
            channels_last: Change to channels last memory format for possible training speed up
        """
        super().__init__()
        self.save_hyperparameters()
        self.arch = arch
        self.optimizer = optimizer
        self.lr = lr
        self.betas = betas
        self.momentum = momentum
        self.weight_decay = weight_decay
        self.scheduler = scheduler
        self.warmup_steps = warmup_steps
        self.n_classes = n_classes
        self.channels_last = channels_last

        # Initialize network
        self.net = AutoModelForImageClassification.from_pretrained(
            model_dict[arch], num_labels=n_classes
        )

        self.train_acc = Accuracy()
        self.val_acc = Accuracy()

        # Change to channel last memory format
        # https://pytorch.org/tutorials/intermediate/memory_format_tutorial.html
        if self.channels_last:
            print("Using channel last memory format")
            self = self.to(memory_format=torch.channels_last)

    def forward(self, x, y):
        if self.channels_last:
            x = x.to(memory_format=torch.channels_last)
        return self.net(pixel_values=x, labels=y)[:2]

    def shared_step(self, batch, mode="train"):
        x, y = batch

        # Pass through network
        loss, logits = self(x, y)
        pred = logits.argmax(1)

        # Get accuracy
        acc = getattr(self, f"{mode}_acc")(pred, y)

        # Log
        self.log(f"{mode}_loss", loss, on_epoch=True)
        self.log(f"{mode}_acc", acc, on_epoch=True)

        return loss

    def training_step(self, batch, _):
        self.log("lr", self.trainer.optimizers[0].param_groups[0]["lr"], prog_bar=True)
        return self.shared_step(batch, "train")

    def validation_step(self, batch, _):
        return self.shared_step(batch, "val")

    def test_step(self, batch, _):
        return self.shared_step(batch, "test")

    def configure_optimizers(self):
        # Initialize optimizer
        if self.optimizer == "adam":
            optimizer = Adam(
                self.net.parameters(),
                lr=self.lr,
                betas=self.betas,
                weight_decay=self.weight_decay,
            )
        elif self.optimizer == "adamw":
            optimizer = AdamW(
                self.net.parameters(),
                lr=self.lr,
                betas=self.betas,
                weight_decay=self.weight_decay,
            )
        elif self.optimizer == "sgd":
            optimizer = SGD(
                self.net.parameters(),
                lr=self.lr,
                momentum=self.momentum,
                weight_decay=self.weight_decay,
            )
        else:
            raise ValueError(
                f"{self.optimizer} is not an available optimizer. Should be one of ['adam', 'adamw', 'sgd']"
            )

        # Initialize learning rate scheduler
        if self.scheduler == "cosine":
            scheduler = get_cosine_schedule_with_warmup(
                optimizer,
                num_training_steps=int(self.trainer.estimated_stepping_batches),
                num_warmup_steps=self.warmup_steps,
            )
        elif self.scheduler == "none":
            scheduler = LambdaLR(optimizer, lambda _: 1)
        else:
            raise ValueError(
                f"{self.scheduler} is not an available optimizer. Should be one of ['cosine', 'none']"
            )

        return {
            "optimizer": optimizer,
            "lr_scheduler": {
                "scheduler": scheduler,
                "interval": "step",
            },
        }
